from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.notation import MuseScoreVisualQaRenderer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render MusicXML to PDF and first-page PNG for local visual QA")
    parser.add_argument("--musicxml", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--renderer", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = MuseScoreVisualQaRenderer(
        renderer_binary=args.renderer,
        timeout_seconds=args.timeout_seconds,
    ).render(args.musicxml, args.output_dir)
    print(json.dumps(result.report(), ensure_ascii=False))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
