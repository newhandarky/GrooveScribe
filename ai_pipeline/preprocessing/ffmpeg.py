from __future__ import annotations

import subprocess
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ai_pipeline.preprocessing.errors import (
    AudioDecodeFailedError,
    FfmpegNotAvailableError,
    NormalizedAudioInvalidError,
    PreprocessingTimeoutError,
)

CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AudioMetadata:
    duration_seconds: float
    sample_rate: int
    channels: int
    format: str
    ffmpeg_version: str | None = None


@dataclass(frozen=True)
class NormalizedAudioResult:
    normalized_path: Path
    metadata: AudioMetadata


class FfmpegAudioNormalizer:
    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        timeout_seconds: int = 300,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def build_command(
        self,
        input_path: Path,
        output_path: Path,
        target_sample_rate: int = 44_100,
        channels: int = 2,
    ) -> list[str]:
        return [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(target_sample_rate),
            "-codec:a",
            "pcm_s16le",
            str(output_path),
        ]

    def normalize(
        self,
        input_path: Path,
        output_dir: Path,
        target_sample_rate: int = 44_100,
        channels: int = 2,
    ) -> NormalizedAudioResult:
        if not input_path.exists():
            raise AudioDecodeFailedError(f"input audio does not exist: {input_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "normalized.wav"
        command = self.build_command(input_path, output_path, target_sample_rate, channels)

        completed = self._run(command)
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            message = stderr or f"ffmpeg failed with exit code {completed.returncode}"
            raise AudioDecodeFailedError(message)

        metadata = self._read_wav_metadata(output_path)
        metadata = AudioMetadata(
            duration_seconds=metadata.duration_seconds,
            sample_rate=metadata.sample_rate,
            channels=metadata.channels,
            format=metadata.format,
            ffmpeg_version=self._read_ffmpeg_version(),
        )
        return NormalizedAudioResult(normalized_path=output_path, metadata=metadata)

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
            raise FfmpegNotAvailableError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise PreprocessingTimeoutError(str(exc)) from exc

    def _read_ffmpeg_version(self) -> str | None:
        try:
            completed = self.runner(
                [self.ffmpeg_binary, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if completed.returncode != 0 or not completed.stdout:
            return None

        return completed.stdout.splitlines()[0]

    def _read_wav_metadata(self, output_path: Path) -> AudioMetadata:
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise NormalizedAudioInvalidError(f"normalized wav was not created: {output_path}")

        try:
            with wave.open(str(output_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                duration_seconds = frames / float(sample_rate) if sample_rate else 0.0
        except (wave.Error, EOFError) as exc:
            raise NormalizedAudioInvalidError(str(exc)) from exc

        if duration_seconds <= 0 or sample_rate <= 0 or channels <= 0:
            raise NormalizedAudioInvalidError("normalized wav metadata is not valid")

        return AudioMetadata(
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
            format="wav",
        )
