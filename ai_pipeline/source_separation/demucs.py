from __future__ import annotations

import shutil
import subprocess
import time
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

from ai_pipeline.source_separation.base import SourceSeparationReport, StemMetadata, StemSet
from ai_pipeline.source_separation.errors import (
    DrumsStemInvalidError,
    DrumsStemNotFoundError,
    SourceSeparationFailedError,
    SourceSeparatorNotAvailableError,
)

CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class DemucsSourceSeparator:
    def __init__(
        self,
        command_prefix: Sequence[str] = ("python", "-m", "demucs"),
        model_name: str = "htdemucs",
        device: str = "auto",
        timeout_seconds: int = 1_800,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.command_prefix = tuple(command_prefix)
        self.model_name = model_name
        self.device = device
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def build_command(self, input_path: Path, demucs_output_dir: Path) -> list[str]:
        command = [
            *self.command_prefix,
            "--two-stems",
            "drums",
            "-n",
            self.model_name,
            "-o",
            str(demucs_output_dir),
        ]
        if self.device != "auto":
            command.extend(["-d", self.device])
        command.append(str(input_path))
        return command

    def separate(self, input_path: Path, output_dir: Path) -> StemSet:
        if not input_path.exists():
            raise SourceSeparationFailedError(f"input audio does not exist: {input_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        demucs_output_dir = output_dir / "demucs"
        command = self.build_command(input_path, demucs_output_dir)

        started_at = time.monotonic()
        completed = self._run(command)
        runtime_seconds = time.monotonic() - started_at
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            message = stderr or f"Demucs failed with exit code {completed.returncode}"
            raise SourceSeparationFailedError(message)

        demucs_drums_path = self._find_demucs_drums_path(demucs_output_dir, input_path)
        stable_drums_path = output_dir / "drums.wav"
        if demucs_drums_path.resolve() != stable_drums_path.resolve():
            shutil.copy2(demucs_drums_path, stable_drums_path)

        metadata = self._read_stem_metadata(stable_drums_path)
        report = SourceSeparationReport(
            separator="demucs",
            model_name=self.model_name,
            device=self.device,
            runtime_seconds=runtime_seconds,
            command=tuple(command),
        )
        return StemSet(drums_path=stable_drums_path, metadata=metadata, report=report)

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
            raise SourceSeparatorNotAvailableError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise SourceSeparationFailedError(str(exc)) from exc

    def _find_demucs_drums_path(self, demucs_output_dir: Path, input_path: Path) -> Path:
        expected = demucs_output_dir / self.model_name / input_path.stem / "drums.wav"
        if expected.exists():
            return expected

        matches = sorted(demucs_output_dir.rglob("drums.wav")) if demucs_output_dir.exists() else []
        if matches:
            return matches[0]

        raise DrumsStemNotFoundError(f"Demucs did not produce drums.wav under {demucs_output_dir}")

    def _read_stem_metadata(self, drums_path: Path) -> StemMetadata:
        if not drums_path.exists() or drums_path.stat().st_size == 0:
            raise DrumsStemInvalidError(f"drums stem is missing or empty: {drums_path}")

        try:
            with wave.open(str(drums_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                duration_seconds = frames / float(sample_rate) if sample_rate else 0.0
        except (wave.Error, EOFError) as exc:
            raise DrumsStemInvalidError(str(exc)) from exc

        if duration_seconds <= 0 or sample_rate <= 0 or channels <= 0:
            raise DrumsStemInvalidError("drums stem metadata is not valid")

        return StemMetadata(
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
            format="wav",
        )
