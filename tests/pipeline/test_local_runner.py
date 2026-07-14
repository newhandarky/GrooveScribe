import json
import math
import struct
import wave
from pathlib import Path

from ai_pipeline.local_runner import LocalPipelineConfig, LocalPipelineRunner


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22_050
    frames = int(sample_rate * 0.25)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(frames):
            value = int(0.2 * 32767 * math.sin(2 * math.pi * 440 * index / sample_rate))
            wav_file.writeframes(struct.pack("<h", value))


def test_local_runner_completes_with_mock_ai(tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    _write_wav(input_path)

    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True)).run(input_path, tmp_path / "job")

    assert result.status == "completed"
    assert (tmp_path / "job" / "audio" / "normalized.wav").exists()
    assert (tmp_path / "job" / "stems" / "drums.wav").exists()
    assert (tmp_path / "job" / "midi" / "raw_drum.mid").exists()
    assert (tmp_path / "job" / "midi" / "processed_drum.mid").exists()
    assert (tmp_path / "job" / "midi" / "drum_events.json").exists()
    assert (tmp_path / "job" / "notation" / "score.musicxml").exists()
    assert (tmp_path / "job" / "notation" / "performance_score.musicxml").exists()
    assert (tmp_path / "job" / "notation" / "performance_score.mid").exists()
    payload = json.loads((tmp_path / "job" / "logs" / "pipeline.json").read_text(encoding="utf-8"))
    assert payload["quality"]["performance_gate"]["verdict"] in {"playable_but_low_confidence", "needs_better_source", "not_ready"}

    log_payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log_payload["status"] == "completed"
    assert [stage["name"] for stage in log_payload["stages"]] == [
        "audio_preprocessing",
        "source_separation",
        "drum_transcription",
        "midi_post_processing",
        "notation_generation",
    ]
    assert log_payload["quality"]["raw_event_count"] == 5
    assert log_payload["quality"]["processed_event_count"] == 5
    assert log_payload["quality"]["processed_drum_counts"] == {"closed_hat": 2, "kick": 2, "snare": 1}
    assert "sparse_transcription" in log_payload["quality"]["quality_flags"]


def test_local_runner_records_failed_stage(tmp_path) -> None:
    input_path = tmp_path / "missing.wav"

    try:
        LocalPipelineRunner().run(input_path, tmp_path / "job")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")
