from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ai_pipeline.local_runner import LocalPipelineConfig, LocalPipelineRunner
from ai_pipeline.runner import build_pipeline_plan
from ai_pipeline.transcription.adtof import resolve_class_thresholds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GrooveScribe local pipeline POC")
    parser.add_argument("--input", type=Path, default=None, help="MP3/WAV input path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("storage/local/jobs/dev-smoke"),
        help="Directory where pipeline artifacts will be written",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the stage plan without processing audio")
    parser.add_argument("--strict-input", action="store_true", help="Fail if --input is missing or does not exist")
    parser.add_argument("--mock-ai", action="store_true", help="Use mock Demucs/ADTOF outputs for local smoke tests")
    parser.add_argument("--title", default="GrooveScribe Drum Draft")
    parser.add_argument("--export-pdf", action="store_true", help="Attempt PDF export if MuseScore CLI is available")
    parser.add_argument("--visual-qa", action="store_true", help="Attempt MuseScore PDF and first-page PNG visual QA")
    parser.add_argument("--require-pdf", action="store_true", help="Fail the pipeline if PDF export fails")
    parser.add_argument("--pdf-renderer", default=None)
    parser.add_argument(
        "--performance-gate-calibration",
        type=Path,
        default=_optional_path(os.environ.get("GROOVESCRIBE_PERFORMANCE_GATE_CALIBRATION")),
        help="Optional redacted gate_calibration.json; without it performance_ready fails closed.",
    )
    parser.add_argument("--demucs-model-name", default="htdemucs")
    parser.add_argument("--demucs-device", default="auto")
    parser.add_argument("--demucs-timeout-seconds", type=int, default=1_800)
    parser.add_argument("--adtof-command-template", default=None)
    parser.add_argument("--adtof-checkpoint", type=Path, default=None)
    parser.add_argument("--adtof-device", default="cpu")
    parser.add_argument("--adtof-threshold", type=float, default=0.5)
    parser.add_argument(
        "--adtof-class-thresholds",
        default=None,
        help="Optional per-class thresholds: kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08",
    )
    parser.add_argument(
        "--adtof-threshold-preset",
        default=None,
        help="Optional opt-in ADTOF threshold preset, e.g. separated_v1",
    )
    parser.add_argument("--adtof-timeout-seconds", type=int, default=1_800)
    parser.add_argument("--tempo-bpm", type=float, default=None, help="Optional MusicXML tempo override for manual evaluation")
    parser.add_argument(
        "--tom-filter-preset",
        default=None,
        help="Optional opt-in MIDI postprocess filter preset, e.g. tom_guard_v1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.dry_run:
        plan = build_pipeline_plan(args.input, args.output_dir)
        print(
            json.dumps(
                {
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
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.strict_input and args.input is None:
        raise SystemExit("--input is required when --strict-input is set")
    if args.input is None:
        raise SystemExit("--input is required unless --dry-run is used")
    if not args.input.exists():
        raise SystemExit(f"input file does not exist: {args.input}")

    config = LocalPipelineConfig(
        mock_ai=args.mock_ai,
        export_pdf=args.export_pdf,
        require_pdf=args.require_pdf,
        visual_qa=args.visual_qa,
        title=args.title,
        demucs_model_name=args.demucs_model_name,
        demucs_device=args.demucs_device,
        demucs_timeout_seconds=args.demucs_timeout_seconds,
        adtof_command_template=args.adtof_command_template,
        adtof_checkpoint_path=args.adtof_checkpoint,
        adtof_device=args.adtof_device,
        adtof_threshold=args.adtof_threshold,
        adtof_class_thresholds=resolve_class_thresholds(
            args.adtof_class_thresholds,
            preset=args.adtof_threshold_preset,
        ),
        adtof_threshold_preset=args.adtof_threshold_preset,
        adtof_timeout_seconds=args.adtof_timeout_seconds,
        tom_filter_preset=args.tom_filter_preset,
        tempo_bpm=args.tempo_bpm,
        pdf_renderer=args.pdf_renderer,
        performance_gate_calibration=_load_json(args.performance_gate_calibration),
    )
    result = LocalPipelineRunner(config).run(args.input, args.output_dir)
    print(
        json.dumps(
            {
                "status": result.status,
                "failed_stage": result.failed_stage,
                "output_dir": str(result.output_dir),
                "log_path": str(result.log_path),
                "artifacts": {name: str(path) for name, path in result.artifacts.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status == "completed" else 1


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _load_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
