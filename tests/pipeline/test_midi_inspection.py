from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from scripts.inspect_midi import inspect_midi
from scripts.inspect_pipeline_artifacts import inspect_pipeline_artifacts


def test_inspect_midi_reports_histogram_and_mapping(tmp_path: Path) -> None:
    midi_path = tmp_path / "raw.mid"
    write_drum_midi(
        midi_path,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
            ProcessedDrumEvent(tick=960, note=10, drum="unknown", velocity=80),
        ),
        ticks_per_beat=480,
    )

    report = inspect_midi(midi_path)

    assert report["event_count"] == 3
    assert report["schema_version"] == "2.0"
    assert report["note_histogram"] == {"10": 1, "36": 1, "38": 1}
    assert report["mapped_drum_counts"] == {"kick": 1, "snare": 1}
    assert report["unmapped_event_count"] == 1
    assert report["quality_flags"] == ["sparse_transcription", "too_few_events"]


def test_inspect_midi_reports_quality_flags_for_mostly_tom_output(tmp_path: Path) -> None:
    midi_path = tmp_path / "mostly_tom.mid"
    write_drum_midi(
        midi_path,
        (
            ProcessedDrumEvent(tick=0, note=45, drum="tom", velocity=100),
            ProcessedDrumEvent(tick=480, note=45, drum="tom", velocity=100),
            ProcessedDrumEvent(tick=960, note=45, drum="tom", velocity=100),
            ProcessedDrumEvent(tick=1440, note=45, drum="tom", velocity=100),
        ),
        ticks_per_beat=480,
    )

    report = inspect_midi(midi_path)

    assert report["event_count"] == 4
    assert report["mapped_drum_counts"] == {"tom": 4}
    assert "hihat_missing_likely" in report["quality_flags"]
    assert "mostly_tom_output" in report["quality_flags"]
    assert "no_snare_detected" in report["quality_flags"]


def test_inspect_pipeline_artifacts_combines_raw_and_processed_quality(tmp_path: Path) -> None:
    raw_midi = tmp_path / "raw.mid"
    processed_midi = tmp_path / "processed.mid"
    write_drum_midi(
        raw_midi,
        (
            ProcessedDrumEvent(tick=0, note=35, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=480, note=47, drum="tom", velocity=90),
            ProcessedDrumEvent(tick=960, note=47, drum="tom", velocity=90),
            ProcessedDrumEvent(tick=1440, note=47, drum="tom", velocity=90),
        ),
        ticks_per_beat=480,
    )
    write_drum_midi(
        processed_midi,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=480, note=45, drum="tom", velocity=90),
            ProcessedDrumEvent(tick=960, note=45, drum="tom", velocity=90),
            ProcessedDrumEvent(tick=1440, note=45, drum="tom", velocity=90),
        ),
        ticks_per_beat=480,
    )

    report = inspect_pipeline_artifacts(raw_midi, processed_midi)

    assert report["quality"]["raw_event_count"] == 4
    assert report["quality"]["processed_event_count"] == 4
    assert report["quality"]["raw_note_histogram"] == {"35": 1, "47": 3}
    assert report["quality"]["processed_drum_counts"] == {"kick": 1, "tom": 3}
    assert "mostly_tom_output" in report["quality"]["quality_flags"]
