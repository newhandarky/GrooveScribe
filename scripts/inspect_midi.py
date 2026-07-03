from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect raw or processed drum MIDI artifacts.")
    parser.add_argument("midi_path", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON. This is the default output shape.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = inspect_midi(args.midi_path)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def inspect_midi(midi_path: Path) -> dict:
    midi = parse_midi(midi_path)
    note_histogram = Counter(event.note for event in midi.notes)
    mapped_counts: Counter[str] = Counter()
    unmapped_count = 0
    for event in midi.notes:
        mapping = map_to_general_midi_drum(event.note)
        if mapping is None:
            unmapped_count += 1
            continue
        mapped_counts[mapping.drum] += 1

    return {
        "schema_version": "1.0",
        "path_name": midi_path.name,
        "event_count": len(midi.notes),
        "ticks_per_beat": midi.ticks_per_beat,
        "tempo_bpm": midi.tempo_bpm,
        "time_signature": midi.time_signature,
        "note_histogram": {str(key): value for key, value in sorted(note_histogram.items())},
        "mapped_drum_counts": dict(sorted(mapped_counts.items())),
        "unmapped_event_count": unmapped_count,
    }


if __name__ == "__main__":
    raise SystemExit(main())
