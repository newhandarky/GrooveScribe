from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from scripts.redaction import find_unsafe_tokens
from scripts.run_true_ai_smoke_baseline import BaselineConfig, run_baseline

_REPO_ROOT = Path(__file__).resolve().parents[1]
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
DEFAULT_THRESHOLDS = ("0.2", "0.3", "0.4", "0.5", "0.6")
MIN_CANDIDATE_EVENT_COUNT = 4
BLOCKING_CANDIDATE_FLAGS = {
    "no_usable_groove",
    "sparse_transcription",
    "too_few_events",
    "mostly_tom_output",
    "no_snare_detected",
}
DEFAULT_FIXTURES = (
    _REPO_ROOT / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_clean_drum_pattern.wav",
    _REPO_ROOT
    / "tests"
    / "pipeline"
    / "fixtures"
    / "audio"
    / "synthetic_separated_kick_snare_hat_pattern.wav",
)


@dataclass(frozen=True)
class QualityMatrixConfig:
    fixtures: tuple[Path, ...]
    output_dir: Path
    thresholds: tuple[str, ...]
    ai_python: str
    demucs_device: str
    adtof_command_template: str | None
    adtof_checkpoint: str | None
    adtof_device: str
    timeout_seconds: int
    adtof_class_thresholds: str | None = None
    adtof_threshold_preset: str | None = None
    tom_filter_preset: str | None = None
    external_fixture: Path | None = None
    export_pdf: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run true-AI quality matrix across fixtures and ADTOF thresholds.")
    parser.add_argument("--fixtures", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/groovescribe-true-ai-quality-matrix"))
    parser.add_argument("--thresholds", default=",".join(DEFAULT_THRESHOLDS))
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", sys.executable))
    parser.add_argument("--demucs-device", default=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"))
    parser.add_argument("--adtof-command-template", default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"))
    parser.add_argument("--adtof-checkpoint", default=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"))
    parser.add_argument("--adtof-device", default=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"))
    parser.add_argument("--adtof-class-thresholds", default=os.environ.get("GROOVESCRIBE_ADTOF_CLASS_THRESHOLDS"))
    parser.add_argument("--adtof-threshold-preset", default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD_PRESET"))
    parser.add_argument("--tom-filter-preset", default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--external-fixture", type=Path, default=_optional_path(os.environ.get("GROOVESCRIBE_AUTHORIZED_REAL_DRUM_FIXTURE")))
    parser.add_argument("--no-export-pdf", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_quality_matrix(
        QualityMatrixConfig(
            fixtures=tuple(args.fixtures or DEFAULT_FIXTURES),
            output_dir=args.output_dir,
            thresholds=_parse_thresholds(args.thresholds),
            ai_python=args.ai_python,
            demucs_device=args.demucs_device,
            adtof_command_template=args.adtof_command_template,
            adtof_checkpoint=args.adtof_checkpoint,
            adtof_device=args.adtof_device,
            timeout_seconds=args.timeout_seconds,
            adtof_class_thresholds=args.adtof_class_thresholds,
            adtof_threshold_preset=args.adtof_threshold_preset,
            tom_filter_preset=args.tom_filter_preset,
            external_fixture=args.external_fixture,
            export_pdf=not args.no_export_pdf,
        )
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output_dir_name": report["output_dir_name"],
                "matrix_report_name": "matrix_report.json",
            },
            indent=2,
        )
    )
    return 0 if report["status"] in {"completed", "completed_with_failures", "blocked", "skipped"} else 1


def run_quality_matrix(
    config: QualityMatrixConfig,
    *,
    process_runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    checked = checked_at or datetime.now(UTC)
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    fixture_entries = [_fixture_entry(path, source="repo") for path in config.fixtures]
    if config.external_fixture is not None:
        fixture_entries.append(_fixture_entry(config.external_fixture, source="external"))

    fixtures: list[dict[str, Any]] = []
    for fixture in fixture_entries:
        if not fixture["path"].exists():
            fixtures.append(
                {
                    "fixture": fixture["display"],
                    "source": fixture["source"],
                    "status": "skipped",
                    "reason": "external_fixture_missing" if fixture["source"] == "external" else "fixture_missing",
                    "runs": [],
                }
            )
            continue

        runs = [
            _run_threshold(
                config,
                fixture_path=fixture["path"],
                fixture_label=fixture["label"],
                threshold=threshold,
                output_dir=output_dir,
                process_runner=process_runner,
                checked_at=checked,
            )
            for threshold in config.thresholds
        ]
        fixtures.append(
            {
                "fixture": fixture["display"],
                "source": fixture["source"],
                "status": _fixture_status(runs),
                "runs": runs,
            }
        )

    report = {
        "schema_version": "1.0",
        "status": _overall_status(fixtures),
        "checked_at": checked.isoformat(),
        "output_dir_name": output_dir.name,
        "thresholds": list(config.thresholds),
        "adtof_class_thresholds": config.adtof_class_thresholds,
        "adtof_threshold_preset": config.adtof_threshold_preset,
        "tom_filter_preset": config.tom_filter_preset,
        "fixtures": fixtures,
        "summary": _summary(fixtures),
    }
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        report["status"] = "failed"
    (output_dir / "matrix_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _run_threshold(
    config: QualityMatrixConfig,
    *,
    fixture_path: Path,
    fixture_label: str,
    threshold: str,
    output_dir: Path,
    process_runner: ProcessRunner,
    checked_at: datetime,
) -> dict[str, Any]:
    run_id = f"{fixture_label}-threshold-{_slug(threshold)}"
    result = run_baseline(
        BaselineConfig(
            input_path=fixture_path,
            output_root=output_dir,
            run_id=run_id,
            ai_python=config.ai_python,
            demucs_device=config.demucs_device,
            adtof_command_template=config.adtof_command_template,
            adtof_checkpoint=config.adtof_checkpoint,
            adtof_device=config.adtof_device,
            adtof_threshold=threshold,
            timeout_seconds=config.timeout_seconds,
            adtof_class_thresholds=config.adtof_class_thresholds,
            adtof_threshold_preset=config.adtof_threshold_preset,
            tom_filter_preset=config.tom_filter_preset,
            export_pdf=config.export_pdf,
        ),
        process_runner=process_runner,
        checked_at=checked_at,
    )
    baseline = _read_json(result.report_path)
    quality = _dict(baseline.get("quality"))
    validation = _dict(baseline.get("validation"))
    musicxml = _musicxml_summary(validation)
    return {
        "threshold": threshold,
        "status": result.status,
        "baseline_ref": baseline.get("baseline_ref", f"baseline:{run_id}"),
        "baseline_report": _relative_to_output(result.report_path, output_dir),
        "return_code": result.return_code,
        "blocked_reason": _safe_text(baseline.get("blocked_reason")),
        "raw_event_count": quality.get("raw_event_count"),
        "processed_event_count": quality.get("processed_event_count"),
        "raw_note_histogram": _dict(quality.get("raw_note_histogram")),
        "processed_drum_counts": _dict(quality.get("processed_drum_counts")),
        "postprocess_filters": _dict(quality.get("postprocess_filters")),
        "quality_flags": _list(quality.get("quality_flags")),
        "warnings": _list(quality.get("warnings")),
        "musicxml": musicxml,
        "minimum_gate": _minimum_gate(quality, run_status=result.status, musicxml=musicxml),
    }


def _minimum_gate(quality: dict[str, Any], *, run_status: str, musicxml: dict[str, Any]) -> dict[str, Any]:
    counts = _dict(quality.get("processed_drum_counts"))
    flags = set(str(item) for item in _list(quality.get("quality_flags")))
    processed_event_count = _int_or_none(quality.get("processed_event_count"))
    blocking_flags = sorted(flags & BLOCKING_CANDIDATE_FLAGS)
    passed = (
        run_status == "completed"
        and processed_event_count is not None
        and processed_event_count >= MIN_CANDIDATE_EVENT_COUNT
        and bool(counts.get("kick"))
        and bool(counts.get("snare"))
        and not blocking_flags
        and bool(musicxml.get("available"))
        and bool(musicxml.get("parseable"))
    )
    return {
        "status": "passed" if passed else "failed",
        "run_completed": run_status == "completed",
        "processed_event_count": processed_event_count,
        "min_event_count": MIN_CANDIDATE_EVENT_COUNT,
        "event_count_sufficient": processed_event_count is not None and processed_event_count >= MIN_CANDIDATE_EVENT_COUNT,
        "kick_present": bool(counts.get("kick")),
        "snare_present": bool(counts.get("snare")),
        "hihat_present": any(counts.get(drum) for drum in ("closed_hat", "pedal_hat", "open_hat")),
        "blocking_flags": blocking_flags,
        "musicxml_available": bool(musicxml.get("available")),
        "musicxml_parseable": bool(musicxml.get("parseable")),
    }


def _summary(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [run for fixture in fixtures for run in fixture.get("runs", [])]
    candidates = [
        {
            "fixture": fixture["fixture"],
            "threshold": run["threshold"],
            "processed_event_count": run.get("processed_event_count"),
            "processed_drum_counts": run.get("processed_drum_counts", {}),
            "quality_flags": run.get("quality_flags", []),
        }
        for fixture in fixtures
        for run in fixture.get("runs", [])
        if _is_candidate_run(run)
    ]
    return {
        "fixture_count": len(fixtures),
        "run_count": len(runs),
        "completed_runs": sum(1 for run in runs if run.get("status") == "completed"),
        "blocked_runs": sum(1 for run in runs if run.get("status") == "blocked"),
        "failed_runs": sum(1 for run in runs if run.get("status") == "failed"),
        "skipped_fixtures": sum(1 for fixture in fixtures if fixture.get("status") == "skipped"),
        "candidate_thresholds": candidates,
    }


def _fixture_status(runs: list[dict[str, Any]]) -> str:
    statuses = {str(run.get("status")) for run in runs}
    if "completed" in statuses and statuses <= {"completed"}:
        return "completed"
    if "completed" in statuses:
        return "completed_with_failures"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    return "unknown"


def _overall_status(fixtures: list[dict[str, Any]]) -> str:
    statuses = {str(fixture.get("status")) for fixture in fixtures}
    if not fixtures or statuses <= {"skipped"}:
        return "skipped"
    if statuses <= {"completed", "skipped"}:
        return "completed"
    if "completed" in statuses or "completed_with_failures" in statuses:
        return "completed_with_failures"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    return "unknown"


def _fixture_entry(path: Path, *, source: str) -> dict[str, Any]:
    resolved = path.expanduser()
    return {
        "path": resolved,
        "source": source,
        "label": _slug(resolved.stem),
        "display": _display_fixture(resolved, source=source),
    }


def _display_fixture(path: Path, *, source: str) -> str:
    if source == "external":
        return f"external:{path.name}"
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return f"external:{path.name}"


def _parse_thresholds(value: str) -> tuple[str, ...]:
    thresholds = tuple(item.strip() for item in value.split(",") if item.strip())
    return thresholds or DEFAULT_THRESHOLDS


def _musicxml_summary(validation: dict[str, Any]) -> dict[str, Any]:
    musicxml = _dict(validation.get("musicxml"))
    if not musicxml:
        return {"available": False, "parseable": False}
    return {
        "available": bool(musicxml.get("available")),
        "parseable": bool(musicxml.get("parseable")),
        "warnings": _list(musicxml.get("warnings")),
    }


def _is_candidate_run(run: dict[str, Any]) -> bool:
    return run.get("status") == "completed" and _dict(run.get("minimum_gate")).get("status") == "passed"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _relative_to_output(path: Path, output_dir: Path) -> str:
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return path.name


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return "[redacted]" if find_unsafe_tokens(text) else text


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug or "unknown"


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
