import subprocess
import wave
from pathlib import Path

from ai_pipeline.source_separation.demucs import DemucsSourceSeparator


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44_100)
        wav_file.writeframes(b"\x00\x00" * 2 * 4_410)


def test_build_command_uses_demucs_two_stem_mode(tmp_path) -> None:
    separator = DemucsSourceSeparator(command_prefix=("demucs",), model_name="htdemucs", device="cpu")
    command = separator.build_command(Path("normalized.wav"), tmp_path / "demucs")

    assert command == [
        "demucs",
        "--two-stems",
        "drums",
        "-n",
        "htdemucs",
        "-o",
        str(tmp_path / "demucs"),
        "-d",
        "cpu",
        "normalized.wav",
    ]


def test_separate_copies_demucs_drums_to_stable_artifact(tmp_path) -> None:
    input_path = tmp_path / "normalized.wav"
    _write_wav(input_path)

    def fake_runner(command, **kwargs):
        output_dir = Path(command[command.index("-o") + 1])
        model_name = command[command.index("-n") + 1]
        demucs_drums = output_dir / model_name / input_path.stem / "drums.wav"
        _write_wav(demucs_drums)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    separator = DemucsSourceSeparator(runner=fake_runner)
    result = separator.separate(input_path, tmp_path / "artifacts")

    assert result.drums_path == tmp_path / "artifacts" / "drums.wav"
    assert result.drums_path.exists()
    assert result.metadata.sample_rate == 44_100
    assert result.metadata.channels == 2
    assert result.report.separator == "demucs"


def test_missing_demucs_output_raises_domain_error(tmp_path) -> None:
    input_path = tmp_path / "normalized.wav"
    _write_wav(input_path)

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    separator = DemucsSourceSeparator(runner=fake_runner)

    try:
        separator.separate(input_path, tmp_path / "artifacts")
    except Exception as exc:
        assert getattr(exc, "code") == "DRUMS_STEM_NOT_FOUND"
    else:
        raise AssertionError("expected DRUMS_STEM_NOT_FOUND")
