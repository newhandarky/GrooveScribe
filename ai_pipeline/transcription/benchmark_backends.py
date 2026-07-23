from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
from string import Formatter
import subprocess
from typing import Protocol

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


@dataclass(frozen=True)
class BackendAvailability:
    backend: str
    ready: bool
    reason_code: str | None = None


class BenchmarkDrumBackend(Protocol):
    name: str

    def availability(self) -> BackendAvailability: ...

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict: ...


class SpectralOnsetDrumBackend:
    """A benchmark-only, dependency-light drum onset baseline using librosa."""

    name = "spectral_onset_spike"

    def availability(self) -> BackendAvailability:
        try:
            import librosa  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            return BackendAvailability(self.name, False, "librosa_runtime_unavailable")
        return BackendAvailability(self.name, True)

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        availability = self.availability()
        if not availability.ready:
            return {"status": "blocked", "backend": self.name, "reason_code": availability.reason_code}
        import librosa
        import numpy as np

        audio, sample_rate = librosa.load(str(drums_stem), sr=None, mono=True)
        hop_length = 512
        onset_frames = librosa.onset.onset_detect(y=audio, sr=sample_rate, hop_length=hop_length, units="frames")
        stft = np.abs(librosa.stft(audio, hop_length=hop_length))
        frequencies = librosa.fft_frequencies(sr=sample_rate)
        events = []
        for frame in onset_frames:
            index = min(int(frame), stft.shape[1] - 1)
            spectrum = stft[:, index]
            drum = _classify_spectrum(spectrum, frequencies)
            seconds = librosa.frames_to_time(index, sr=sample_rate, hop_length=hop_length)
            tick = round(float(seconds) * tempo_bpm / 60.0 * 480)
            note = {"kick": 36, "snare": 38, "hi_hat": 42}[drum]
            events.append(ProcessedDrumEvent(tick=max(0, tick), note=note, drum=drum, velocity=96))
        write_drum_midi(output_midi, tuple(events), ticks_per_beat=480, tempo_bpm=tempo_bpm)
        return {"status": "completed", "backend": self.name, "event_count": len(events)}


class MagentaOnsetsFramesDrumBackend:
    """Benchmark-only adapter for Magenta's official pretrained E-GMD drum model.

    The model command and checkpoint stay in the private runtime environment. The
    adapter deliberately does not provide a fallback: a missing Magenta runtime
    is a blocked benchmark result, never a spectral-onset substitution.
    """

    name = "magenta_onsets_frames_drums"
    command_env = "GROOVESCRIBE_MAGENTA_DRUM_COMMAND_TEMPLATE"
    model_source = "magenta_onsets_frames_e_gmd"
    model_license = "Apache-2.0"

    def __init__(
        self,
        *,
        command_template: str | None = None,
        timeout_seconds: int = 1_800,
        runner=subprocess.run,
    ) -> None:
        self.command_template = command_template if command_template is not None else os.environ.get(self.command_env)
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def availability(self) -> BackendAvailability:
        return _template_availability(
            backend=self.name,
            template=self.command_template,
            unavailable_reason="magenta_onsets_frames_runtime_unavailable",
            invalid_reason="magenta_onsets_frames_command_invalid",
        )

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        availability = self.availability()
        if not availability.ready:
            return {"status": "blocked", "backend": self.name, "reason_code": availability.reason_code}
        if not drums_stem.exists():
            return {"status": "blocked", "backend": self.name, "reason_code": "benchmark_artifact_missing"}
        output_midi.parent.mkdir(parents=True, exist_ok=True)
        try:
            command = _format_template_command(self.command_template or "", drums_stem, output_midi, tempo_bpm)
        except (KeyError, ValueError):
            return {"status": "blocked", "backend": self.name, "reason_code": "magenta_onsets_frames_command_invalid"}
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {"status": "blocked", "backend": self.name, "reason_code": "magenta_onsets_frames_runtime_unavailable"}
        if completed.returncode != 0 or not output_midi.exists():
            return {"status": "blocked", "backend": self.name, "reason_code": "magenta_onsets_frames_transcription_failed"}
        try:
            parsed = parse_midi(output_midi)
        except Exception:
            return {"status": "blocked", "backend": self.name, "reason_code": "magenta_onsets_frames_output_invalid"}
        drums = {
            mapping.drum
            for note in parsed.notes
            if (mapping := map_to_general_midi_drum(note.note)) is not None
        }
        if not parsed.notes or len(drums) < 2:
            return {"status": "blocked", "backend": self.name, "reason_code": "magenta_onsets_frames_multiclass_output_missing"}
        return {
            "status": "completed",
            "backend": self.name,
            "event_count": len(parsed.notes),
            "observed_drum_classes": sorted(drums),
            "model_source": self.model_source,
            "model_license": self.model_license,
        }


class SelfTrainedPrototypeDrumBackend:
    """Benchmark-only adapter for a locally trained, project-controlled model.

    The model command and all training assets live outside the repository. This
    adapter has no heuristic fallback so a missing private runtime is auditable.
    """

    name = "self_trained_prototype_drums"
    command_env = "GROOVESCRIBE_SELF_TRAINED_DRUM_COMMAND_TEMPLATE"
    model_source = "groovescribe_self_trained_prototype_v1"
    model_license = "project-controlled"

    def __init__(
        self,
        *,
        command_template: str | None = None,
        timeout_seconds: int = 900,
        runner=subprocess.run,
    ) -> None:
        self.command_template = command_template if command_template is not None else os.environ.get(self.command_env)
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def availability(self) -> BackendAvailability:
        return _template_availability(
            backend=self.name,
            template=self.command_template,
            unavailable_reason="self_trained_prototype_runtime_unavailable",
            invalid_reason="self_trained_prototype_command_invalid",
        )

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        return _run_template_backend(
            backend=self,
            drums_stem=drums_stem,
            output_midi=output_midi,
            tempo_bpm=tempo_bpm,
            unavailable_reason="self_trained_prototype_runtime_unavailable",
            command_invalid_reason="self_trained_prototype_command_invalid",
            failed_reason="self_trained_prototype_transcription_failed",
            invalid_reason="self_trained_prototype_output_invalid",
            missing_classes_reason="self_trained_prototype_multiclass_output_missing",
        )


class SelfTrainedMulticlassDrumBackend:
    """Benchmark-only adapter for the local multi-class neural baseline."""

    name = "self_trained_multiclass_drums"
    command_env = "GROOVESCRIBE_SELF_TRAINED_MULTICLASS_COMMAND_TEMPLATE"
    model_source = "groovescribe_self_trained_multiclass_v1"
    model_license = "project-controlled"

    def __init__(
        self,
        *,
        command_template: str | None = None,
        timeout_seconds: int = 900,
        runner=subprocess.run,
    ) -> None:
        self.command_template = command_template if command_template is not None else os.environ.get(self.command_env)
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def availability(self) -> BackendAvailability:
        return _template_availability(
            backend=self.name,
            template=self.command_template,
            unavailable_reason="self_trained_multiclass_runtime_unavailable",
            invalid_reason="self_trained_multiclass_command_invalid",
        )

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        return _run_template_backend(
            backend=self,
            drums_stem=drums_stem,
            output_midi=output_midi,
            tempo_bpm=tempo_bpm,
            unavailable_reason="self_trained_multiclass_runtime_unavailable",
            command_invalid_reason="self_trained_multiclass_command_invalid",
            failed_reason="self_trained_multiclass_transcription_failed",
            invalid_reason="self_trained_multiclass_output_invalid",
            missing_classes_reason="self_trained_multiclass_output_missing",
        )


class SelfTrainedMultilabelDrumBackend:
    """Benchmark-only adapter for the source-isolated multi-label frame baseline."""

    name = "self_trained_multilabel_drums"
    command_env = "GROOVESCRIBE_SELF_TRAINED_MULTILABEL_COMMAND_TEMPLATE"
    model_source = "groovescribe_self_trained_multilabel_v2"
    model_license = "project-controlled"

    def __init__(
        self,
        *,
        command_template: str | None = None,
        timeout_seconds: int = 900,
        runner=subprocess.run,
    ) -> None:
        self.command_template = command_template if command_template is not None else os.environ.get(self.command_env)
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def availability(self) -> BackendAvailability:
        return _template_availability(
            backend=self.name,
            template=self.command_template,
            unavailable_reason="self_trained_multilabel_runtime_unavailable",
            invalid_reason="self_trained_multilabel_command_invalid",
        )

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        return _run_template_backend(
            backend=self,
            drums_stem=drums_stem,
            output_midi=output_midi,
            tempo_bpm=tempo_bpm,
            unavailable_reason="self_trained_multilabel_runtime_unavailable",
            command_invalid_reason="self_trained_multilabel_command_invalid",
            failed_reason="self_trained_multilabel_transcription_failed",
            invalid_reason="self_trained_multilabel_output_invalid",
            missing_classes_reason="self_trained_multilabel_multiclass_output_missing",
        )


def get_benchmark_backend(name: str) -> BenchmarkDrumBackend | None:
    backends: tuple[BenchmarkDrumBackend, ...] = (
        SpectralOnsetDrumBackend(),
        MagentaOnsetsFramesDrumBackend(),
        SelfTrainedPrototypeDrumBackend(),
        SelfTrainedMulticlassDrumBackend(),
        SelfTrainedMultilabelDrumBackend(),
    )
    return next((backend for backend in backends if name == backend.name), None)


def _classify_spectrum(spectrum, frequencies) -> str:
    def energy(low: float, high: float) -> float:
        mask = (frequencies >= low) & (frequencies < high)
        return float(spectrum[mask].mean()) if mask.any() else 0.0

    kick = energy(30, 180) * 1.5
    snare = energy(180, 4_000)
    hat = energy(5_000, 14_000) * 1.2
    return max(((kick, "kick"), (snare, "snare"), (hat, "hi_hat")), key=lambda item: item[0])[1]


def _template_availability(
    *,
    backend: str,
    template: str | None,
    unavailable_reason: str,
    invalid_reason: str,
) -> BackendAvailability:
    if not template:
        return BackendAvailability(backend, False, unavailable_reason)
    try:
        command = shlex.split(template)
    except ValueError:
        return BackendAvailability(backend, False, invalid_reason)
    if not command or not _valid_template_fields(template):
        return BackendAvailability(backend, False, invalid_reason)
    executable = command[0]
    if not Path(executable).is_file() and shutil.which(executable) is None:
        return BackendAvailability(backend, False, unavailable_reason)
    return BackendAvailability(backend, True)


def _run_template_backend(
    *,
    backend,
    drums_stem: Path,
    output_midi: Path,
    tempo_bpm: float,
    unavailable_reason: str,
    command_invalid_reason: str,
    failed_reason: str,
    invalid_reason: str,
    missing_classes_reason: str,
) -> dict:
    availability = backend.availability()
    if not availability.ready:
        return {"status": "blocked", "backend": backend.name, "reason_code": availability.reason_code}
    if not drums_stem.exists():
        return {"status": "blocked", "backend": backend.name, "reason_code": "benchmark_artifact_missing"}
    output_midi.parent.mkdir(parents=True, exist_ok=True)
    try:
        command = _format_template_command(backend.command_template or "", drums_stem, output_midi, tempo_bpm)
    except (KeyError, ValueError):
        return {"status": "blocked", "backend": backend.name, "reason_code": command_invalid_reason}
    try:
        completed = backend.runner(command, capture_output=True, text=True, timeout=backend.timeout_seconds, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"status": "blocked", "backend": backend.name, "reason_code": unavailable_reason}
    if completed.returncode != 0 or not output_midi.exists():
        return {"status": "blocked", "backend": backend.name, "reason_code": failed_reason}
    try:
        parsed = parse_midi(output_midi)
    except Exception:
        return {"status": "blocked", "backend": backend.name, "reason_code": invalid_reason}
    drums = {
        mapping.drum
        for note in parsed.notes
        if (mapping := map_to_general_midi_drum(note.note)) is not None
    }
    if not parsed.notes or len(drums) < 3 or not {"kick", "snare"}.issubset(drums):
        return {"status": "blocked", "backend": backend.name, "reason_code": missing_classes_reason}
    return {
        "status": "completed",
        "backend": backend.name,
        "event_count": len(parsed.notes),
        "observed_drum_classes": sorted(drums),
        "model_source": backend.model_source,
        "model_license": backend.model_license,
    }


def _valid_template_fields(template: str) -> bool:
    """Only accept the placeholders the benchmark adapter can safely supply."""

    try:
        fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name is not None}
    except ValueError:
        return False
    return {"input", "output"}.issubset(fields) and fields <= {"input", "output", "tempo_bpm"}


def _format_template_command(template: str, drums_stem: Path, output_midi: Path, tempo_bpm: float) -> list[str]:
    replacements = {"input": str(drums_stem), "output": str(output_midi), "tempo_bpm": f"{tempo_bpm:g}"}
    return [value.format(**replacements) for value in shlex.split(template)]
