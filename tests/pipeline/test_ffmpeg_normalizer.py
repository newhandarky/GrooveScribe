import subprocess
from pathlib import Path

from ai_pipeline.preprocessing.ffmpeg import FfmpegAudioNormalizer


def test_build_command_uses_mvp_audio_settings() -> None:
    normalizer = FfmpegAudioNormalizer(ffmpeg_binary="ffmpeg-test")
    command = normalizer.build_command(Path("input.mp3"), Path("out/normalized.wav"))

    assert command == [
        "ffmpeg-test",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "input.mp3",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-codec:a",
        "pcm_s16le",
        "out/normalized.wav",
    ]


def test_runner_failure_maps_to_decode_error(tmp_path) -> None:
    source = tmp_path / "bad.mp3"
    source.write_bytes(b"not audio")

    def fake_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="decode failed")

    normalizer = FfmpegAudioNormalizer(runner=fake_runner)

    try:
        normalizer.normalize(source, tmp_path / "out")
    except Exception as exc:
        assert getattr(exc, "code") == "AUDIO_DECODE_FAILED"
        assert "decode failed" in str(exc)
    else:
        raise AssertionError("expected AUDIO_DECODE_FAILED")
