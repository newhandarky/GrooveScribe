import json
from pathlib import Path

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.postprocessor import MidiPostProcessor
from ai_pipeline.midi.simple_midi import parse_midi, write_drum_midi
from ai_pipeline.midi.types import MidiPostProcessConfig, ProcessedDrumEvent
from ai_pipeline.transcription.midi_validation import count_note_on_events


def _write_raw_midi(path: Path) -> None:
    events = (
        ProcessedDrumEvent(tick=0, note=35, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=58, note=36, drum="kick", velocity=90),
        ProcessedDrumEvent(tick=122, note=38, drum="snare", velocity=80),
        ProcessedDrumEvent(tick=241, note=42, drum="closed_hat", velocity=70),
    )
    write_drum_midi(path, events, ticks_per_beat=480, tempo_bpm=120.0, default_duration_ticks=60)


def test_general_midi_drum_mapping() -> None:
    assert map_to_general_midi_drum(35).note == 36
    assert map_to_general_midi_drum(38).drum == "snare"
    assert map_to_general_midi_drum(42).drum == "closed_hat"
    assert map_to_general_midi_drum(10) is None


def test_postprocessor_quantizes_dedupes_and_writes_artifacts(tmp_path) -> None:
    raw_midi = tmp_path / "raw_drum.mid"
    _write_raw_midi(raw_midi)

    processor = MidiPostProcessor(
        MidiPostProcessConfig(
            grid_subdivisions_per_beat=4,
            dedupe_window_ticks=120,
            velocity_floor=1,
            default_duration_ticks=60,
        )
    )
    result = processor.process(raw_midi, tmp_path / "out")

    assert result.processed_midi_path.exists()
    assert result.drum_events_path.exists()
    assert count_note_on_events(result.processed_midi_path) == 3
    assert [event.tick for event in result.events] == [0, 120, 240]
    assert [event.drum for event in result.events] == ["kick", "snare", "closed_hat"]

    payload = json.loads(result.drum_events_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["event_count"] == 3
    assert payload["events"][0]["midi_note"] == 36
    assert payload["raw_note_histogram"] == {"35": 1, "36": 1, "38": 1, "42": 1}
    assert payload["processed_drum_counts"] == {"closed_hat": 1, "kick": 1, "snare": 1}
    assert "too_few_events" in payload["warnings"]


def test_postprocessor_warns_for_sparse_and_unbalanced_output(tmp_path) -> None:
    raw_midi = tmp_path / "raw_toms.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=480, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=960, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=1440, note=45, drum="tom", velocity=100),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.processed_drum_counts == {"tom": 4}
    assert "mostly_tom_output" in result.report.warnings
    assert "hihat_missing_likely" in result.report.warnings


def test_parse_processed_midi_round_trip(tmp_path) -> None:
    midi_path = tmp_path / "processed.mid"
    events = (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),)
    write_drum_midi(midi_path, events, ticks_per_beat=480)

    parsed = parse_midi(midi_path)
    assert parsed.ticks_per_beat == 480
    assert len(parsed.notes) == 1
    assert parsed.notes[0].note == 36
