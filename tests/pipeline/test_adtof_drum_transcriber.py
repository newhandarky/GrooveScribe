import subprocess
import wave
from pathlib import Path

from ai_pipeline.transcription.adtof import AdtofDrumTranscriber
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
    assert command == ["adtof", "--in", "drums.wav", "--out", str(tmp_path / "raw_drum.mid"), "--checkpoint", "model.ckpt"]


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
