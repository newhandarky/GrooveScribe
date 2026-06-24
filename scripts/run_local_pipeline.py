from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.runner import build_pipeline_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GrooveScribe local pipeline dry-run")
    parser.add_argument("--input", type=Path, default=None, help="MP3/WAV input path for future runs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("storage/local/jobs/dev-smoke"),
        help="Directory where pipeline artifacts will be written in future runs",
    )
    parser.add_argument(
        "--strict-input",
        action="store_true",
        help="Fail if --input is missing or does not exist",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.strict_input and args.input is None:
        raise SystemExit("--input is required when --strict-input is set")

    if args.input is not None and not args.input.exists():
        raise SystemExit(f"input file does not exist: {args.input}")

    plan = build_pipeline_plan(args.input, args.output_dir)
    payload = {
        "status": "dry_run",
        "input_path": str(plan.input_path) if plan.input_path else None,
        "output_dir": str(plan.output_dir),
        "stages": [
            {
                "name": stage.name,
                "input_artifact": stage.input_artifact,
                "output_artifact": stage.output_artifact,
                "adapter": stage.adapter,
            }
            for stage in plan.stages
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
