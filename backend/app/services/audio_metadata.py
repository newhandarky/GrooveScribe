from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


class AudioMetadataInspectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioMetadata:
    duration_seconds: float
    sample_rate: int | None = None
    channels: int | None = None


class AudioMetadataInspector:
    def inspect(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str,
        timeout_seconds: int,
    ) -> AudioMetadata:
        suffix = Path(filename).suffix.lower()
        if suffix == ".wav" or content_type in {"audio/wav", "audio/wave", "audio/x-wav"}:
            try:
                return self._inspect_wav(content)
            except AudioMetadataInspectionError:
                return self._inspect_with_ffprobe(content, suffix or ".wav", timeout_seconds)

        return self._inspect_with_ffprobe(content, suffix or ".audio", timeout_seconds)

    def _inspect_wav(self, content: bytes) -> AudioMetadata:
        try:
            with wave.open(BytesIO(content), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                if frame_rate <= 0 or frame_count <= 0:
                    raise AudioMetadataInspectionError("invalid wav frame metadata")
                return AudioMetadata(
                    duration_seconds=frame_count / float(frame_rate),
                    sample_rate=frame_rate,
                    channels=wav_file.getnchannels(),
                )
        except (EOFError, wave.Error, OSError) as exc:
            raise AudioMetadataInspectionError("wav metadata unreadable") from exc

    def _inspect_with_ffprobe(
        self,
        content: bytes,
        suffix: str,
        timeout_seconds: int,
    ) -> AudioMetadata:
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                completed = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration:stream=codec_type,sample_rate,channels",
                        "-of",
                        "json",
                        temp_file.name,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise AudioMetadataInspectionError("ffprobe metadata unreadable") from exc

        try:
            payload = json.loads(completed.stdout)
            duration = float(payload["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AudioMetadataInspectionError("ffprobe duration unreadable") from exc

        if duration <= 0:
            raise AudioMetadataInspectionError("duration must be positive")

        audio_stream = next(
            (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"),
            {},
        )
        sample_rate = self._safe_int(audio_stream.get("sample_rate"))
        channels = self._safe_int(audio_stream.get("channels"))
        return AudioMetadata(duration_seconds=duration, sample_rate=sample_rate, channels=channels)

    def _safe_int(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
