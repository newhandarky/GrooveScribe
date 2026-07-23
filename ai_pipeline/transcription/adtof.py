from __future__ import annotations

import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from ai_pipeline.transcription.base import (
    DrumTranscriptionReport,
    MidiMetadata,
    TranscriptionResult,
)
from ai_pipeline.transcription.errors import (
    DrumTranscriberNotAvailableError,
    DrumTranscriptionFailedError,
    RawMidiEmptyError,
)
from ai_pipeline.transcription.midi_validation import count_note_on_events

CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
ADTOF_CLASS_THRESHOLD_ORDER = ("kick", "snare", "tom", "closed_hat", "cymbal")
ADTOF_CLASS_THRESHOLD_NOTES = {
    "kick": 35,
    "snare": 38,
    "tom": 47,
    "closed_hat": 42,
    "cymbal": 49,
}
ADTOF_CLASS_THRESHOLD_PRESETS = {
    "separated_v1": {
        "kick": 0.06,
        "snare": 0.04,
        "tom": 0.18,
        "closed_hat": 0.06,
        "cymbal": 0.08,
    },
    # Benchmark-only follow-up to separated_v1.  Attribution showed that the
    # full-mix raw output has no closed-hat matches, so this experiment changes
    # exactly that class while preserving every other separated_v1 threshold.
    "separated_hihat_v1": {
        "kick": 0.06,
        "snare": 0.04,
        "tom": 0.18,
        "closed_hat": 0.03,
        "cymbal": 0.08,
    },
}
ADTOF_CLASS_ALIASES = {
    "hat": "closed_hat",
    "hihat": "closed_hat",
    "closed_hihat": "closed_hat",
}

DEFAULT_COMMAND_TEMPLATE = (
    sys.executable,
    "-m",
    "adtof",
    "transcribe",
    "--input",
    "{input}",
    "--output",
    "{output}",
    "--device",
    "{device}",
    "--threshold",
    "{threshold}",
)


class AdtofDrumTranscriber:
    def __init__(
        self,
        command_template: Sequence[str] = DEFAULT_COMMAND_TEMPLATE,
        model_name: str = "adtof-pytorch",
        checkpoint_path: Path | None = None,
        device: str = "cpu",
        threshold: float = 0.5,
        class_thresholds: dict[str, float] | None = None,
        timeout_seconds: int = 1_800,
        min_event_count: int = 1,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.command_template = tuple(command_template)
        self.model_name = model_name
        self.checkpoint_path = checkpoint_path
        self.device = device
        self.threshold = threshold
        self.class_thresholds = normalize_class_thresholds(class_thresholds)
        self.timeout_seconds = timeout_seconds
        self.min_event_count = min_event_count
        self.runner = runner

    @classmethod
    def from_command_template_string(
        cls,
        command_template: str,
        **kwargs,
    ) -> "AdtofDrumTranscriber":
        return cls(command_template=tuple(shlex.split(command_template)), **kwargs)

    def build_command(self, drums_path: Path, raw_midi_path: Path) -> list[str]:
        replacements = {
            "input": str(drums_path),
            "output": str(raw_midi_path),
            "device": self.device,
            "threshold": str(self.threshold),
            "thresholds": class_thresholds_csv(self.class_thresholds) if self.class_thresholds else "",
            "checkpoint": str(self.checkpoint_path) if self.checkpoint_path else "",
        }
        command = [part.format(**replacements) for part in self.command_template]
        template_text = " ".join(self.command_template)
        if self.class_thresholds:
            command = _strip_scalar_threshold(command)
            if "{thresholds}" not in template_text and "--thresholds" not in self.command_template:
                command.extend(["--thresholds", class_thresholds_csv(self.class_thresholds)])
        elif "{threshold}" not in template_text and "--threshold" not in self.command_template:
            command.extend(["--threshold", str(self.threshold)])
        if self.checkpoint_path is not None and "{checkpoint}" not in template_text:
            command.extend(["--checkpoint", str(self.checkpoint_path)])
        return [part for part in command if part]

    def transcribe(self, drums_path: Path, output_dir: Path) -> TranscriptionResult:
        if not drums_path.exists():
            raise DrumTranscriptionFailedError(f"drums audio does not exist: {drums_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        raw_midi_path = output_dir / "raw_drum.mid"
        command = self.build_command(drums_path, raw_midi_path)

        started_at = time.monotonic()
        completed = self._run(command)
        runtime_seconds = time.monotonic() - started_at
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            message = stderr or f"ADTOF failed with exit code {completed.returncode}"
            raise DrumTranscriptionFailedError(message)

        event_count = count_note_on_events(raw_midi_path)
        if event_count < self.min_event_count:
            raise RawMidiEmptyError(f"raw MIDI contains {event_count} note-on events")

        report = DrumTranscriptionReport(
            transcriber="adtof-pytorch",
            model_name=self.model_name,
            device=self.device,
            threshold=self.threshold,
            runtime_seconds=runtime_seconds,
            command=tuple(command),
            class_thresholds=self.class_thresholds,
            checkpoint_path=str(self.checkpoint_path) if self.checkpoint_path else None,
        )
        return TranscriptionResult(
            raw_midi_path=raw_midi_path,
            metadata=MidiMetadata(event_count=event_count),
            report=report,
        )

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DrumTranscriberNotAvailableError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise DrumTranscriptionFailedError(str(exc)) from exc


def parse_class_thresholds(value: str | None) -> dict[str, float] | None:
    if not value:
        return None
    thresholds: dict[str, float] = {}
    for item in value.split(","):
        part = item.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"class threshold must use name=value: {part}")
        name, raw_value = part.split("=", 1)
        key = _canonical_class_name(name.strip())
        if key in thresholds:
            raise ValueError(f"duplicate class threshold: {key}")
        try:
            threshold = float(raw_value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid threshold for {key}: {raw_value}") from exc
        if not 0 <= threshold <= 1:
            raise ValueError(f"threshold for {key} must be between 0 and 1")
        thresholds[key] = threshold
    return normalize_class_thresholds(thresholds)


def class_thresholds_for_preset(name: str | None) -> dict[str, float] | None:
    if not name:
        return None
    key = name.strip().lower().replace("-", "_")
    if key not in ADTOF_CLASS_THRESHOLD_PRESETS:
        raise ValueError(
            f"unsupported ADTOF threshold preset '{name}'; supported presets: "
            f"{', '.join(sorted(ADTOF_CLASS_THRESHOLD_PRESETS))}"
        )
    return normalize_class_thresholds(ADTOF_CLASS_THRESHOLD_PRESETS[key])


def resolve_class_thresholds(
    value: str | None = None,
    *,
    preset: str | None = None,
) -> dict[str, float] | None:
    if value and preset:
        raise ValueError("--adtof-class-thresholds and --adtof-threshold-preset cannot be combined")
    if preset:
        return class_thresholds_for_preset(preset)
    return parse_class_thresholds(value)


def class_thresholds_text_for_preset(name: str) -> str:
    thresholds = class_thresholds_for_preset(name)
    assert thresholds is not None
    return class_thresholds_csv(thresholds)


def normalize_class_thresholds(value: dict[str, float] | None) -> dict[str, float] | None:
    if value is None:
        return None
    normalized: dict[str, float] = {}
    for name, threshold in value.items():
        key = _canonical_class_name(str(name))
        if not 0 <= float(threshold) <= 1:
            raise ValueError(f"threshold for {key} must be between 0 and 1")
        normalized[key] = float(threshold)
    missing = [name for name in ADTOF_CLASS_THRESHOLD_ORDER if name not in normalized]
    if missing:
        raise ValueError(f"missing class thresholds: {', '.join(missing)}")
    return {name: normalized[name] for name in ADTOF_CLASS_THRESHOLD_ORDER}


def class_thresholds_csv(value: dict[str, float]) -> str:
    normalized = normalize_class_thresholds(value)
    assert normalized is not None
    return ",".join(_format_threshold(normalized[name]) for name in ADTOF_CLASS_THRESHOLD_ORDER)


def _strip_scalar_threshold(command: list[str]) -> list[str]:
    stripped: list[str] = []
    skip_next = False
    for part in command:
        if skip_next:
            skip_next = False
            continue
        if part == "--threshold":
            skip_next = True
            continue
        if part.startswith("--threshold="):
            continue
        stripped.append(part)
    return stripped


def _canonical_class_name(value: str) -> str:
    key = value.strip().lower().replace("-", "_")
    key = ADTOF_CLASS_ALIASES.get(key, key)
    if key not in ADTOF_CLASS_THRESHOLD_ORDER:
        raise ValueError(
            f"unsupported ADTOF class threshold '{value}'; supported classes: "
            f"{', '.join(ADTOF_CLASS_THRESHOLD_ORDER)}"
        )
    return key


def _format_threshold(value: float) -> str:
    return f"{value:.6g}"
