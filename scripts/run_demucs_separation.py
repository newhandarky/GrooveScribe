from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.source_separation import DemucsSourceSeparator, SourceSeparationError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Separate drums stem from normalized.wav with Demucs")
    parser.add_argument("--input", type=Path, required=True, help="normalized.wav path")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output artifact directory")
    parser.add_argument("--model-name", default="htdemucs")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--timeout-seconds", type=int, default=1_800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    separator = DemucsSourceSeparator(
        model_name=args.model_name,
        device=args.device,
        timeout_seconds=args.timeout_seconds,
    )

    try:
        result = separator.separate(args.input, args.output_dir)
    except SourceSeparationError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}, indent=2))
        return 1

    print(
        json.dumps(
            {
                "status": "completed",
                "drums_path": str(result.drums_path),
                "metadata": {
                    "duration_seconds": result.metadata.duration_seconds,
                    "sample_rate": result.metadata.sample_rate,
                    "channels": result.metadata.channels,
                    "format": result.metadata.format,
                },
                "report": {
                    "separator": result.report.separator,
                    "model_name": result.report.model_name,
                    "device": result.report.device,
                    "runtime_seconds": result.report.runtime_seconds,
                    "command": list(result.report.command),
                    "warnings": list(result.report.warnings),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
