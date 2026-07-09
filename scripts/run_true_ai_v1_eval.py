from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from scripts.redaction import find_unsafe_tokens
from scripts.run_true_ai_mvp_eval import (
    DEFAULT_SCALAR_THRESHOLD,
    DEFAULT_THRESHOLD_PRESET,
    DEFAULT_WAV_FIXTURE,
    MvpEvalConfig,
    run_mvp_eval,
)

DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-true-ai-v1-eval")
DEFAULT_TOM_FILTER_PRESET = "tom_guard_v1"
REPORT_NAME = "v1_eval_report.json"
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class V1EvalConfig:
    output_dir: Path
    wav_fixture: Path
    ai_python: str
    demucs_device: str
    adtof_command_template: str | None
    adtof_checkpoint: str | None
    adtof_device: str
    timeout_seconds: int
    scalar_threshold: str = DEFAULT_SCALAR_THRESHOLD
    threshold_preset: str | None = DEFAULT_THRESHOLD_PRESET
    tom_filter_preset: str | None = DEFAULT_TOM_FILTER_PRESET
    mp3_fixture: Path | None = None
    external_fixture: Path | None = None
    export_pdf: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GrooveScribe V1 true-AI product-readiness eval.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--wav-fixture", type=Path, default=DEFAULT_WAV_FIXTURE)
    parser.add_argument("--mp3-fixture", type=Path, default=None)
    parser.add_argument("--external-fixture", type=Path, default=_optional_path(os.environ.get("GROOVESCRIBE_AUTHORIZED_REAL_DRUM_FIXTURE")))
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", sys.executable))
    parser.add_argument("--demucs-device", default=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"))
    parser.add_argument("--adtof-command-template", default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"))
    parser.add_argument("--adtof-checkpoint", default=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"))
    parser.add_argument("--adtof-device", default=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"))
    parser.add_argument("--scalar-threshold", default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", DEFAULT_SCALAR_THRESHOLD))
    parser.add_argument("--threshold-preset", default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD_PRESET", DEFAULT_THRESHOLD_PRESET))
    parser.add_argument("--tom-filter-preset", default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET", DEFAULT_TOM_FILTER_PRESET))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--export-pdf", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_v1_eval(
        V1EvalConfig(
            output_dir=args.output_dir,
            wav_fixture=args.wav_fixture,
            mp3_fixture=args.mp3_fixture,
            external_fixture=args.external_fixture,
            ai_python=args.ai_python,
            demucs_device=args.demucs_device,
            adtof_command_template=args.adtof_command_template,
            adtof_checkpoint=args.adtof_checkpoint,
            adtof_device=args.adtof_device,
            scalar_threshold=args.scalar_threshold,
            threshold_preset=args.threshold_preset,
            tom_filter_preset=args.tom_filter_preset,
            timeout_seconds=args.timeout_seconds,
            export_pdf=args.export_pdf,
        )
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output_dir_name": report["output_dir_name"],
                "v1_eval_report_name": REPORT_NAME,
            },
            indent=2,
        )
    )
    return 0 if report["status"] in {"completed", "completed_with_failures", "blocked", "skipped"} else 1


def run_v1_eval(
    config: V1EvalConfig,
    *,
    process_runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    checked = checked_at or datetime.now(UTC)
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mvp_report = run_mvp_eval(
        MvpEvalConfig(
            output_dir=output_dir,
            wav_fixture=config.wav_fixture,
            mp3_fixture=config.mp3_fixture,
            external_fixture=config.external_fixture,
            ai_python=config.ai_python,
            demucs_device=config.demucs_device,
            adtof_command_template=config.adtof_command_template,
            adtof_checkpoint=config.adtof_checkpoint,
            adtof_device=config.adtof_device,
            scalar_threshold=config.scalar_threshold,
            threshold_preset=config.threshold_preset,
            tom_filter_preset=config.tom_filter_preset,
            compare_tom_filter=bool(config.tom_filter_preset),
            timeout_seconds=config.timeout_seconds,
            export_pdf=config.export_pdf,
        ),
        process_runner=process_runner,
        checked_at=checked,
    )
    rows = [_v1_fixture_row(item) for item in mvp_report.get("fixtures", [])]
    report = {
        "schema_version": "1.0",
        "status": mvp_report.get("status"),
        "checked_at": checked.isoformat(),
        "output_dir_name": output_dir.name,
        "product_preset": {
            "threshold_preset": config.threshold_preset,
            "tom_filter_preset": config.tom_filter_preset,
        },
        "v1_readiness": _v1_readiness(rows),
        "fixtures": rows,
        "mvp_eval_ref": "mvp_eval_report.json",
    }
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        report["status"] = "failed"
    (output_dir / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _v1_fixture_row(item: dict[str, Any]) -> dict[str, Any]:
    verdict = _dict(item.get("quality_verdict"))
    gate = _dict(item.get("candidate_gate"))
    musicxml = _dict(item.get("musicxml"))
    human_correctable = (
        item.get("status") == "completed"
        and gate.get("status") == "passed"
        and bool(musicxml.get("parseable"))
        and int(verdict.get("usability_score") or 0) >= 4
    )
    return {
        "fixture": item.get("fixture"),
        "input_format": item.get("input_format"),
        "variant": item.get("variant"),
        "status": item.get("status"),
        "human_correctable": human_correctable,
        "primary_blocker": None if human_correctable else _primary_blocker(item),
        "quality_verdict": verdict,
        "processed_drum_counts": _dict(item.get("processed_drum_counts")),
        "musicxml": musicxml,
        "postprocess_filters": _dict(item.get("postprocess_filters")),
        "manual_eval_seed": {
            "artifact_ref": item.get("baseline_ref"),
            "baseline_report_ref": item.get("baseline_report"),
            "human_correctable": "",
            "primary_blocker": "",
            "review_notes_ref": "",
        },
    }


def _v1_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    product_rows = [row for row in rows if row.get("variant") != "filter_off"]
    repo_rows = [row for row in product_rows if not str(row.get("fixture", "")).startswith("external:")]
    external_rows = [row for row in product_rows if str(row.get("fixture", "")).startswith("external:")]
    return {
        "repo_fixture_human_correctable": any(row.get("human_correctable") for row in repo_rows),
        "external_fixture_count": len(external_rows),
        "external_human_correctable_count": sum(1 for row in external_rows if row.get("human_correctable")),
        "v1_complete": bool(repo_rows) and any(row.get("human_correctable") for row in repo_rows) and any(
            row.get("human_correctable") for row in external_rows
        ),
    }


def _primary_blocker(item: dict[str, Any]) -> str:
    if item.get("status") != "completed":
        return str(item.get("status") or "not_completed")
    gate = _dict(item.get("candidate_gate"))
    blocking = gate.get("blocking_flags")
    if isinstance(blocking, list) and blocking:
        return str(blocking[0])
    musicxml = _dict(item.get("musicxml"))
    if not musicxml.get("parseable"):
        return "musicxml_unparseable"
    verdict = _dict(item.get("quality_verdict"))
    limitations = verdict.get("limitations")
    if isinstance(limitations, list) and limitations:
        return str(limitations[0])
    return "manual_review_required"


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
