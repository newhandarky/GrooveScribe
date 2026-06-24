from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.midi import MidiPostProcessConfig, MidiPostProcessingError, MidiPostProcessor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-process raw_drum.mid into processed MIDI and drum_events.json")
    parser.add_argument("--input", type=Path, required=True, help="raw_drum.mid path")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output artifact directory")
    parser.add_argument("--grid-subdivisions-per-beat", type=int, default=4)
    parser.add_argument("--dedupe-window-ticks", type=int, default=30)
    parser.add_argument("--velocity-floor", type=int, default=1)
    parser.add_argument("--default-duration-ticks", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MidiPostProcessConfig(
        grid_subdivisions_per_beat=args.grid_subdivisions_per_beat,
        dedupe_window_ticks=args.dedupe_window_ticks,
        velocity_floor=args.velocity_floor,
        default_duration_ticks=args.default_duration_ticks,
    )
    processor = MidiPostProcessor(config=config)

    try:
        result = processor.process(args.input, args.output_dir)
    except MidiPostProcessingError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}, indent=2))
        return 1

    print(
        json.dumps(
            {
                "status": "completed",
                "processed_midi_path": str(result.processed_midi_path),
                "drum_events_path": str(result.drum_events_path),
                "report": {
                    "input_event_count": result.report.input_event_count,
                    "output_event_count": result.report.output_event_count,
                    "dropped_event_count": result.report.dropped_event_count,
                    "quantize_grid": result.report.quantize_grid,
                    "estimated_bpm": result.report.estimated_bpm,
                    "time_signature": result.report.time_signature,
                    "warnings": list(result.report.warnings),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
