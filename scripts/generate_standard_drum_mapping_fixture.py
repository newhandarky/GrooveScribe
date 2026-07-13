from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.notation import MusicXmlGenerator, NotationConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a fixed Standard Drum Kit MusicXML mapping fixture")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    events_path = args.output_dir / "drum_events.json"
    events = [
        (0, "kick", 36),
        (240, "closed_hat", 42),
        (480, "snare", 38),
        (720, "open_hat", 46),
        (960, "tom", 45),
        (1440, "cymbal", 49),
    ]
    events_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "ticks_per_beat": 480,
                "estimated_bpm": 120.0,
                "time_signature": "4/4",
                "event_count": len(events),
                "events": [
                    {
                        "index": index,
                        "tick": tick,
                        "beat": tick / 480,
                        "drum": drum,
                        "midi_note": midi_note,
                        "velocity": 100,
                    }
                    for index, (tick, drum, midi_note) in enumerate(events)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = MusicXmlGenerator(
        NotationConfig(
            title="GrooveScribe Standard Drum Mapping Fixture",
            chart_mode="full_transcription",
        )
    ).generate(events_path, args.output_dir)
    print(json.dumps({"status": "completed", "musicxml_name": result.musicxml_path.name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
