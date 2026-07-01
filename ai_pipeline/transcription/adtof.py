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
        timeout_seconds: int = 1_800,
        min_event_count: int = 1,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.command_template = tuple(command_template)
        self.model_name = model_name
        self.checkpoint_path = checkpoint_path
        self.device = device
        self.threshold = threshold
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
            "checkpoint": str(self.checkpoint_path) if self.checkpoint_path else "",
        }
        command = [part.format(**replacements) for part in self.command_template]
        template_text = " ".join(self.command_template)
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
