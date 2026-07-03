from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.midi.quality import inspect_midi_quality


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
    return inspect_midi_quality(midi_path)


if __name__ == "__main__":
    raise SystemExit(main())
