import subprocess
import wave
from pathlib import Path

from ai_pipeline.transcription.adtof import (
    AdtofDrumTranscriber,
    class_thresholds_csv,
    class_thresholds_for_preset,
    parse_class_thresholds,
    resolve_class_thresholds,
)
from ai_pipeline.transcription.midi_validation import count_note_on_events


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44_100)
        wav_file.writeframes(b"\x00\x00" * 2 * 4_410)


def _write_simple_midi(path: Path, include_note: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    track = bytearray()
    if include_note:
        track.extend(b"\x00\x90\x24\x40")
        track.extend(b"\x83\x60\x80\x24\x00")
    track.extend(b"\x00\xff\x2f\x00")
    data = bytearray()
    data.extend(b"MThd")
    data.extend((6).to_bytes(4, "big"))
    data.extend((0).to_bytes(2, "big"))
    data.extend((1).to_bytes(2, "big"))
    data.extend((480).to_bytes(2, "big"))
    data.extend(b"MTrk")
    data.extend(len(track).to_bytes(4, "big"))
    data.extend(track)
    path.write_bytes(bytes(data))


def test_count_note_on_events() -> None:
    midi_path = Path("/tmp/groovescribe-test-note.mid")
    _write_simple_midi(midi_path)
    assert count_note_on_events(midi_path) == 1


def test_build_command_supports_checkpoint_append(tmp_path) -> None:
    transcriber = AdtofDrumTranscriber(
        command_template=("adtof", "--in", "{input}", "--out", "{output}"),
        checkpoint_path=Path("model.ckpt"),
        device="mps",
        threshold=0.42,
    )
    command = transcriber.build_command(Path("drums.wav"), tmp_path / "raw_drum.mid")
    assert command == [
        "adtof",
        "--in",
        "drums.wav",
        "--out",
        str(tmp_path / "raw_drum.mid"),
        "--threshold",
        "0.42",
        "--checkpoint",
        "model.ckpt",
    ]


def test_build_command_keeps_scalar_threshold_compatible(tmp_path) -> None:
    transcriber = AdtofDrumTranscriber(
        command_template=("adtof", "--audio", "{input}", "--out", "{output}"),
        threshold=0.42,
    )

    command = transcriber.build_command(Path("drums.wav"), tmp_path / "raw_drum.mid")

    assert command == ["adtof", "--audio", "drums.wav", "--out", str(tmp_path / "raw_drum.mid"), "--threshold", "0.42"]


def test_parse_class_thresholds_uses_adtof_label_order() -> None:
    thresholds = parse_class_thresholds("kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08")

    assert thresholds == {
        "kick": 0.06,
        "snare": 0.04,
        "tom": 0.12,
        "closed_hat": 0.06,
        "cymbal": 0.08,
    }
    assert class_thresholds_csv(thresholds) == "0.06,0.04,0.12,0.06,0.08"


def test_parse_separated_v1_threshold_preset() -> None:
    thresholds = class_thresholds_for_preset("separated_v1")

    assert thresholds == {
        "kick": 0.06,
        "snare": 0.04,
        "tom": 0.18,
        "closed_hat": 0.06,
        "cymbal": 0.08,
    }


def test_parse_separated_hihat_v1_changes_only_closed_hat_threshold() -> None:
    baseline = class_thresholds_for_preset("separated_v1")
    thresholds = class_thresholds_for_preset("separated_hihat_v1")

    assert baseline is not None and thresholds is not None
    assert thresholds["closed_hat"] == 0.03
    assert {key: value for key, value in thresholds.items() if key != "closed_hat"} == {
        key: value for key, value in baseline.items() if key != "closed_hat"
    }
    assert class_thresholds_csv(thresholds) == "0.06,0.04,0.18,0.03,0.08"


def test_resolve_class_thresholds_rejects_preset_and_explicit_thresholds() -> None:
    try:
        resolve_class_thresholds("kick=0.06,snare=0.04,tom=0.18,closed_hat=0.06,cymbal=0.08", preset="separated_v1")
    except ValueError as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("expected preset plus explicit thresholds to fail")


def test_build_command_supports_per_class_thresholds(tmp_path) -> None:
    transcriber = AdtofDrumTranscriber(
        command_template=("adtof", "--audio", "{input}", "--out", "{output}"),
        threshold=0.06,
        class_thresholds=parse_class_thresholds("kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08"),
    )

    command = transcriber.build_command(Path("drums.wav"), tmp_path / "raw_drum.mid")

    assert command == [
        "adtof",
        "--audio",
        "drums.wav",
        "--out",
        str(tmp_path / "raw_drum.mid"),
        "--thresholds",
        "0.06,0.04,0.12,0.06,0.08",
    ]


def test_build_command_replaces_thresholds_placeholder(tmp_path) -> None:
    transcriber = AdtofDrumTranscriber(
        command_template=("adtof", "--audio", "{input}", "--out", "{output}", "--thresholds", "{thresholds}"),
        class_thresholds=parse_class_thresholds("kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08"),
    )

    command = transcriber.build_command(Path("drums.wav"), tmp_path / "raw_drum.mid")

    assert command[-2:] == ["--thresholds", "0.06,0.04,0.12,0.06,0.08"]


def test_build_command_uses_per_class_thresholds_over_scalar_placeholder(tmp_path) -> None:
    transcriber = AdtofDrumTranscriber(
        command_template=(
            "adtof",
            "--audio",
            "{input}",
            "--out",
            "{output}",
            "--threshold",
            "{threshold}",
        ),
        threshold=0.06,
        class_thresholds=parse_class_thresholds("kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08"),
    )

    command = transcriber.build_command(Path("drums.wav"), tmp_path / "raw_drum.mid")

    assert "--threshold" not in command
    assert command[-2:] == ["--thresholds", "0.06,0.04,0.12,0.06,0.08"]


def test_transcribe_validates_raw_midi_output(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    _write_wav(drums_path)

    def fake_runner(command, **kwargs):
        raw_midi = Path(command[command.index("--output") + 1])
        _write_simple_midi(raw_midi)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    transcriber = AdtofDrumTranscriber(runner=fake_runner)
    result = transcriber.transcribe(drums_path, tmp_path / "midi")

    assert result.raw_midi_path == tmp_path / "midi" / "raw_drum.mid"
    assert result.metadata.event_count == 1
    assert result.report.transcriber == "adtof-pytorch"


def test_empty_raw_midi_maps_to_domain_error(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    _write_wav(drums_path)

    def fake_runner(command, **kwargs):
        raw_midi = Path(command[command.index("--output") + 1])
        _write_simple_midi(raw_midi, include_note=False)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    transcriber = AdtofDrumTranscriber(runner=fake_runner)

    try:
        transcriber.transcribe(drums_path, tmp_path / "midi")
    except Exception as exc:
        assert getattr(exc, "code") == "RAW_MIDI_EMPTY"
    else:
        raise AssertionError("expected RAW_MIDI_EMPTY")
