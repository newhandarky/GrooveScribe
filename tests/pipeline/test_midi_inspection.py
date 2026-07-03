from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from scripts.inspect_midi import inspect_midi


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
    assert report["note_histogram"] == {"10": 1, "36": 1, "38": 1}
    assert report["mapped_drum_counts"] == {"kick": 1, "snare": 1}
    assert report["unmapped_event_count"] == 1
