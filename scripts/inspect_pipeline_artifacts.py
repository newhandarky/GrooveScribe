from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.inspect_midi import inspect_midi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect raw and processed MIDI pipeline artifacts.")
    parser.add_argument("--raw-midi", type=Path, required=True)
    parser.add_argument("--processed-midi", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(inspect_pipeline_artifacts(args.raw_midi, args.processed_midi), ensure_ascii=False, indent=2))
    return 0


def inspect_pipeline_artifacts(raw_midi_path: Path, processed_midi_path: Path) -> dict:
    raw = inspect_midi(raw_midi_path)
    processed = inspect_midi(processed_midi_path)
    warnings = sorted(set(raw["quality_flags"]) | set(processed["quality_flags"]))

    return {
        "schema_version": "1.0",
        "raw": raw,
        "processed": processed,
        "quality": {
            "raw_event_count": raw["event_count"],
            "processed_event_count": processed["event_count"],
            "raw_note_histogram": raw["note_histogram"],
            "processed_drum_counts": processed["mapped_drum_counts"],
            "duration_seconds": processed["duration_seconds"],
            "tempo_bpm": processed["tempo_bpm"],
            "estimated_measure_count": processed["estimated_measure_count"],
            "quality_flags": warnings,
            "warnings": warnings,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
