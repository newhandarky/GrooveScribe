from __future__ import annotations

import json
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "tests" / "pipeline" / "fixtures" / "audio"
MANIFEST_PATH = ROOT / "tests" / "pipeline" / "fixtures" / "manifest.json"
SAMPLE_RATE = 44_100


def main() -> int:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = [
        _write_clean_drum_pattern(AUDIO_DIR / "synthetic_clean_drum_pattern.wav"),
        _write_quiet_drum_pattern(AUDIO_DIR / "synthetic_quiet_drum_pattern.wav"),
        _write_silence(AUDIO_DIR / "synthetic_silence.wav"),
        _write_invalid_audio(AUDIO_DIR / "invalid_audio.wav"),
    ]
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_by": "scripts/generate_test_fixtures.py",
                "license_note": "Programmatically generated test fixtures. No third-party audio material is included.",
                "fixtures": fixtures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(fixtures)} fixtures to {AUDIO_DIR}")
    return 0


def _write_clean_drum_pattern(path: Path) -> dict:
    duration_seconds = 2.0
    frames = [0.0] * int(SAMPLE_RATE * duration_seconds)
    for beat in (0.0, 1.0):
        _add_kick(frames, beat)
    for beat in (0.5, 1.5):
        _add_snare(frames, beat)
    for index in range(8):
        _add_hat(frames, index * 0.25)
    _write_wav(path, frames)
    return _fixture_entry(
        path,
        purpose="Clean synthetic drum-like pattern for local runner and preprocessing smoke tests.",
        expected_behavior="ffmpeg normalization succeeds; mock pipeline can complete end to end.",
        duration_seconds=duration_seconds,
        valid_audio=True,
    )


def _write_quiet_drum_pattern(path: Path) -> dict:
    duration_seconds = 2.0
    frames = [0.0] * int(SAMPLE_RATE * duration_seconds)
    for beat in (0.0, 1.0):
        _add_kick(frames, beat, gain=0.18)
    for beat in (0.5, 1.5):
        _add_snare(frames, beat, gain=0.12)
    _write_wav(path, frames)
    return _fixture_entry(
        path,
        purpose="Low-level synthetic drum-like pattern for future low-confidence and sensitivity checks.",
        expected_behavior="ffmpeg normalization succeeds; true model output may be sparse or low confidence.",
        duration_seconds=duration_seconds,
        valid_audio=True,
    )


def _write_silence(path: Path) -> dict:
    duration_seconds = 1.0
    frames = [0.0] * int(SAMPLE_RATE * duration_seconds)
    _write_wav(path, frames)
    return _fixture_entry(
        path,
        purpose="Valid silent WAV for edge-case handling.",
        expected_behavior="ffmpeg normalization succeeds; true transcription should produce empty or failed output.",
        duration_seconds=duration_seconds,
        valid_audio=True,
    )


def _write_invalid_audio(path: Path) -> dict:
    path.write_bytes(b"this is not a valid wav file")
    return _fixture_entry(
        path,
        purpose="Invalid WAV extension with non-audio bytes for decode failure checks.",
        expected_behavior="ffmpeg normalization fails with AUDIO_DECODE_FAILED.",
        duration_seconds=None,
        valid_audio=False,
    )


def _add_kick(frames: list[float], start_seconds: float, gain: float = 0.8) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    length = int(0.16 * SAMPLE_RATE)
    for i in range(length):
        idx = start + i
        if idx >= len(frames):
            break
        envelope = math.exp(-9 * i / length)
        frequency = 90 - 45 * i / length
        frames[idx] += gain * envelope * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE)


def _add_snare(frames: list[float], start_seconds: float, gain: float = 0.45) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    length = int(0.09 * SAMPLE_RATE)
    rng = random.Random(38)
    for i in range(length):
        idx = start + i
        if idx >= len(frames):
            break
        envelope = math.exp(-7 * i / length)
        noise = rng.uniform(-1.0, 1.0)
        tone = math.sin(2 * math.pi * 190 * i / SAMPLE_RATE)
        frames[idx] += gain * envelope * (0.75 * noise + 0.25 * tone)


def _add_hat(frames: list[float], start_seconds: float, gain: float = 0.22) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    length = int(0.035 * SAMPLE_RATE)
    rng = random.Random(int(start_seconds * 10_000) + 42)
    for i in range(length):
        idx = start + i
        if idx >= len(frames):
            break
        envelope = math.exp(-12 * i / length)
        frames[idx] += gain * envelope * rng.uniform(-1.0, 1.0)


def _write_wav(path: Path, frames: list[float]) -> None:
    peak = max(1.0, max(abs(value) for value in frames))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        for value in frames:
            sample = int(max(-1.0, min(1.0, value / peak * 0.9)) * 32767)
            wav_file.writeframes(struct.pack("<h", sample))


def _fixture_entry(path: Path, purpose: str, expected_behavior: str, duration_seconds: float | None, valid_audio: bool) -> dict:
    return {
        "path": str(path.relative_to(ROOT)),
        "type": "audio/wav" if valid_audio else "invalid-audio",
        "duration_seconds": duration_seconds,
        "source": "generated",
        "third_party_material": False,
        "purpose": purpose,
        "expected_behavior": expected_behavior,
    }


if __name__ == "__main__":
    raise SystemExit(main())
