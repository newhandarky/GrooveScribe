from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.transcription.adtof import resolve_class_thresholds
from ai_pipeline.transcription import AdtofDrumTranscriber, DrumTranscriptionError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe drums.wav into raw_drum.mid with ADTOF")
    parser.add_argument("--input", type=Path, required=True, help="drums.wav path")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output MIDI artifact directory")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument(
        "--class-thresholds",
        default=None,
        help="Optional per-class thresholds: kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08",
    )
    parser.add_argument("--threshold-preset", default=None, help="Optional opt-in threshold preset, e.g. separated_v1")
    parser.add_argument("--timeout-seconds", type=int, default=1_800)
    parser.add_argument(
        "--command-template",
        default=None,
        help="Optional command template. Supports {input}, {output}, {device}, {threshold}, {checkpoint}.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kwargs = {
        "checkpoint_path": args.checkpoint,
        "device": args.device,
        "threshold": args.threshold,
        "class_thresholds": resolve_class_thresholds(args.class_thresholds, preset=args.threshold_preset),
        "timeout_seconds": args.timeout_seconds,
    }
    if args.command_template:
        transcriber = AdtofDrumTranscriber.from_command_template_string(args.command_template, **kwargs)
    else:
        transcriber = AdtofDrumTranscriber(**kwargs)

    try:
        result = transcriber.transcribe(args.input, args.output_dir)
    except DrumTranscriptionError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}, indent=2))
        return 1

    print(
        json.dumps(
            {
                "status": "completed",
                "raw_midi_path": str(result.raw_midi_path),
                "metadata": {
                    "event_count": result.metadata.event_count,
                    "format": result.metadata.format,
                },
                "report": {
                    "transcriber": result.report.transcriber,
                    "model_name": result.report.model_name,
                    "device": result.report.device,
                    "threshold": result.report.threshold,
                    "class_thresholds": result.report.class_thresholds,
                    "runtime_seconds": result.report.runtime_seconds,
                    "checkpoint_path": result.report.checkpoint_path,
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
