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

from ai_pipeline.midi.quality import evaluate_drum_draft_quality
from ai_pipeline.transcription.adtof import (
    class_thresholds_csv,
    resolve_class_thresholds,
)
from scripts.redaction import find_unsafe_tokens
from scripts.run_true_ai_smoke_baseline import BaselineConfig, run_baseline

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAV_FIXTURE = (
    _REPO_ROOT / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_separated_kick_snare_hat_pattern.wav"
)
DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-true-ai-mvp-eval")
DEFAULT_THRESHOLD_PRESET = "separated_v1"
DEFAULT_SCALAR_THRESHOLD = "0.06"
REPORT_NAME = "mvp_eval_report.json"
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

BLOCKING_CANDIDATE_FLAGS = {
    "no_usable_groove",
    "sparse_transcription",
    "too_few_events",
    "mostly_tom_output",
    "no_snare_detected",
}
MIN_CANDIDATE_EVENT_COUNT = 4


@dataclass(frozen=True)
class MvpEvalConfig:
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
    adtof_class_thresholds: str | None = None
    tom_filter_preset: str | None = None
    compare_tom_filter: bool = False
    mp3_fixture: Path | None = None
    external_fixture: Path | None = None
    export_pdf: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run true-AI MVP eval for WAV, MP3, and optional authorized audio.")
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
    parser.add_argument("--adtof-class-thresholds", default=os.environ.get("GROOVESCRIBE_ADTOF_CLASS_THRESHOLDS"))
    parser.add_argument("--tom-filter-preset", default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET"))
    parser.add_argument(
        "--compare-tom-filter",
        action="store_true",
        help="Run each fixture once without tom filter and once with --tom-filter-preset.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--no-export-pdf", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_mvp_eval(
        MvpEvalConfig(
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
            adtof_class_thresholds=args.adtof_class_thresholds,
            tom_filter_preset=args.tom_filter_preset,
            compare_tom_filter=args.compare_tom_filter,
            timeout_seconds=args.timeout_seconds,
            export_pdf=not args.no_export_pdf,
        )
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output_dir_name": report["output_dir_name"],
                "mvp_eval_report_name": REPORT_NAME,
            },
            indent=2,
        )
    )
    return 0 if report["status"] in {"completed", "completed_with_failures", "blocked", "skipped"} else 1


def run_mvp_eval(
    config: MvpEvalConfig,
    *,
    process_runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    checked = checked_at or datetime.now(UTC)
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    class_thresholds = resolve_class_thresholds(config.adtof_class_thresholds, preset=config.threshold_preset)
    class_thresholds_text = class_thresholds_csv(class_thresholds) if class_thresholds else None

    fixtures = [_fixture_entry("repo_wav", config.wav_fixture, source="repo")]
    mp3_entry = _mp3_fixture_entry(config, output_dir=output_dir, process_runner=process_runner)
    fixtures.append(mp3_entry)
    if config.external_fixture is not None:
        fixtures.append(_fixture_entry("external_real_audio", config.external_fixture, source="external"))

    runs = []
    for fixture in fixtures:
        for variant, tom_filter_preset in _run_variants(config):
            runs.append(
                _run_fixture(
                    fixture,
                    config,
                    output_dir=output_dir,
                    class_thresholds_text=class_thresholds_text,
                    variant=variant,
                    tom_filter_preset=tom_filter_preset,
                    process_runner=process_runner,
                    checked_at=checked,
                )
            )
    report = {
        "schema_version": "1.0",
        "status": _overall_status(runs),
        "checked_at": checked.isoformat(),
        "output_dir_name": output_dir.name,
        "threshold_preset": config.threshold_preset,
        "scalar_threshold": config.scalar_threshold,
        "class_thresholds": class_thresholds,
        "tom_filter_preset": config.tom_filter_preset,
        "compare_tom_filter": config.compare_tom_filter,
        "fixtures": runs,
        "summary": _summary(runs),
    }
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        report["status"] = "failed"
    (output_dir / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _mp3_fixture_entry(
    config: MvpEvalConfig,
    *,
    output_dir: Path,
    process_runner: ProcessRunner,
) -> dict[str, Any]:
    if config.mp3_fixture is not None:
        return _fixture_entry("repo_mp3", config.mp3_fixture, source="repo")
    generated_path = output_dir / "generated_fixtures" / f"{config.wav_fixture.stem}.mp3"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(config.wav_fixture),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(generated_path),
    ]
    try:
        completed = process_runner(command, capture_output=True, text=True, timeout=120, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "label": "repo_mp3",
            "source": "generated_from_repo",
            "input_format": "mp3",
            "display": "generated:synthetic_separated_kick_snare_hat_pattern.mp3",
            "path": generated_path,
            "generation_status": "blocked",
            "generation_error": exc.__class__.__name__,
        }
    if completed.returncode != 0 or not generated_path.exists():
        return {
            "label": "repo_mp3",
            "source": "generated_from_repo",
            "input_format": "mp3",
            "display": "generated:synthetic_separated_kick_snare_hat_pattern.mp3",
            "path": generated_path,
            "generation_status": "failed",
            "generation_error": "ffmpeg_mp3_generation_failed",
        }
    return {
        "label": "repo_mp3",
        "source": "generated_from_repo",
        "input_format": "mp3",
        "display": "generated:synthetic_separated_kick_snare_hat_pattern.mp3",
        "path": generated_path,
        "generation_status": "completed",
    }


def _run_fixture(
    fixture: dict[str, Any],
    config: MvpEvalConfig,
    *,
    output_dir: Path,
    class_thresholds_text: str | None,
    variant: str,
    tom_filter_preset: str | None,
    process_runner: ProcessRunner,
    checked_at: datetime,
) -> dict[str, Any]:
    if fixture.get("generation_status") in {"blocked", "failed"}:
        return _skipped_fixture(fixture, reason=str(fixture.get("generation_error")), variant=variant, tom_filter_preset=tom_filter_preset)
    path = Path(fixture["path"])
    if not path.exists():
        return _skipped_fixture(fixture, reason="fixture_missing", variant=variant, tom_filter_preset=tom_filter_preset)
    run_id = _slug(f"{fixture['label']}-{variant}")
    result = run_baseline(
        BaselineConfig(
            input_path=path,
            output_root=output_dir,
            run_id=run_id,
            ai_python=config.ai_python,
            demucs_device=config.demucs_device,
            adtof_command_template=config.adtof_command_template,
            adtof_checkpoint=config.adtof_checkpoint,
            adtof_device=config.adtof_device,
            adtof_threshold=config.scalar_threshold,
            timeout_seconds=config.timeout_seconds,
            adtof_class_thresholds=class_thresholds_text if config.adtof_class_thresholds else None,
            adtof_threshold_preset=config.threshold_preset if not config.adtof_class_thresholds else None,
            tom_filter_preset=tom_filter_preset,
            export_pdf=config.export_pdf,
        ),
        process_runner=process_runner,
        checked_at=checked_at,
    )
    baseline = _read_json(result.report_path)
    quality = _dict(baseline.get("quality"))
    validation = _dict(baseline.get("validation"))
    musicxml = _musicxml_summary(validation)
    quality_verdict = _dict(quality.get("quality_verdict")) or evaluate_drum_draft_quality(
        processed_drum_counts=_dict(quality.get("processed_drum_counts")),
        processed_event_count=_int_or_none(quality.get("processed_event_count")),
        quality_flags=_list(quality.get("quality_flags")),
        musicxml_available=bool(musicxml.get("available")),
        musicxml_parseable=bool(musicxml.get("parseable")),
        run_completed=result.status == "completed",
    )
    candidate_gate = _dict(quality_verdict.get("candidate_gate"))
    artifact_refs = {
        name: _dict(item).get("path")
        for name, item in _dict(baseline.get("artifacts")).items()
        if name in {"raw_midi", "processed_midi", "drum_events", "musicxml", "pipeline_log"}
    }
    return {
        "fixture": fixture["display"],
        "variant": variant,
        "tom_filter_preset": tom_filter_preset,
        "source": fixture["source"],
        "input_format": fixture["input_format"],
        "status": result.status,
        "baseline_ref": baseline.get("baseline_ref", f"baseline:{run_id}"),
        "baseline_report": _relative_to_output(result.report_path, output_dir),
        "raw_event_count": quality.get("raw_event_count"),
        "processed_event_count": quality.get("processed_event_count"),
        "raw_note_histogram": _dict(quality.get("raw_note_histogram")),
        "processed_drum_counts": _dict(quality.get("processed_drum_counts")),
        "tom_ratio": _tom_ratio(_dict(quality.get("processed_drum_counts"))),
        "postprocess_filters": _dict(quality.get("postprocess_filters")),
        "quality_flags": _list(quality.get("quality_flags")),
        "blocking_quality_flags": _list(candidate_gate.get("blocking_flags")),
        "musicxml": musicxml,
        "candidate_gate": candidate_gate,
        "quality_verdict": quality_verdict,
        "usability_score": quality_verdict.get("usability_score"),
        "artifact_refs": artifact_refs,
    }


def _skipped_fixture(
    fixture: dict[str, Any],
    *,
    reason: str,
    variant: str,
    tom_filter_preset: str | None,
) -> dict[str, Any]:
    return {
        "fixture": fixture["display"],
        "variant": variant,
        "tom_filter_preset": tom_filter_preset,
        "source": fixture["source"],
        "input_format": fixture["input_format"],
        "status": "skipped",
        "reason": reason,
        "raw_note_histogram": {},
        "processed_drum_counts": {},
        "tom_ratio": None,
        "postprocess_filters": {},
        "musicxml": {"available": False, "parseable": False},
        "candidate_gate": {"status": "failed"},
        "usability_score": 1,
        "artifact_refs": {},
    }


def _run_variants(config: MvpEvalConfig) -> tuple[tuple[str, str | None], ...]:
    if config.compare_tom_filter and config.tom_filter_preset:
        return (("filter_off", None), (config.tom_filter_preset, config.tom_filter_preset))
    if config.tom_filter_preset:
        return ((config.tom_filter_preset, config.tom_filter_preset),)
    return (("filter_off", None),)


def _fixture_entry(label: str, path: Path, *, source: str) -> dict[str, Any]:
    return {
        "label": label,
        "source": source,
        "input_format": path.suffix.lower().lstrip(".") or "unknown",
        "display": _display_path(path, source=source),
        "path": path.expanduser(),
    }


def _display_path(path: Path, *, source: str) -> str:
    if source == "external":
        return f"external:{path.name}"
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return f"generated:{path.name}"


def _musicxml_summary(validation: dict[str, Any]) -> dict[str, Any]:
    musicxml = _dict(validation.get("musicxml"))
    if not musicxml:
        return {"available": False, "parseable": False}
    return {
        "available": bool(musicxml.get("available")),
        "parseable": bool(musicxml.get("parseable")),
        "warnings": _list(musicxml.get("warnings")),
    }


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [run for run in runs if _dict(run.get("candidate_gate")).get("status") == "passed"]
    return {
        "fixture_count": len(runs),
        "completed_runs": sum(1 for run in runs if run.get("status") == "completed"),
        "candidate_count": len(candidates),
        "best_usability_score": max((int(run.get("usability_score") or 0) for run in runs), default=0),
        "filter_comparison": _filter_comparison(runs),
        "candidate_outputs": [
            {
                "fixture": run.get("fixture"),
                "variant": run.get("variant"),
                "input_format": run.get("input_format"),
                "processed_drum_counts": run.get("processed_drum_counts"),
                "tom_ratio": run.get("tom_ratio"),
                "postprocess_filters": run.get("postprocess_filters"),
                "usability_score": run.get("usability_score"),
            }
            for run in candidates
        ],
    }


def _filter_comparison(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_fixture_format: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for run in runs:
        key = (str(run.get("fixture")), str(run.get("input_format")))
        by_fixture_format.setdefault(key, {})[str(run.get("variant"))] = run
    comparisons = []
    for (fixture, input_format), variants in sorted(by_fixture_format.items()):
        if "filter_off" not in variants:
            continue
        baseline = variants["filter_off"]
        for variant, filtered in sorted(variants.items()):
            if variant == "filter_off":
                continue
            baseline_counts = _dict(baseline.get("processed_drum_counts"))
            filtered_counts = _dict(filtered.get("processed_drum_counts"))
            comparisons.append(
                {
                    "fixture": fixture,
                    "input_format": input_format,
                    "filter_variant": variant,
                    "baseline_tom_count": int(baseline_counts.get("tom", 0)),
                    "filtered_tom_count": int(filtered_counts.get("tom", 0)),
                    "baseline_to_filtered_tom_delta": max(
                        0,
                        int(baseline_counts.get("tom", 0)) - int(filtered_counts.get("tom", 0)),
                    ),
                    "filter_report_dropped_tom_count": _filter_dropped_tom_count(filtered),
                    "baseline_usability_score": baseline.get("usability_score"),
                    "filtered_usability_score": filtered.get("usability_score"),
                    "filtered_verdict": _dict(filtered.get("quality_verdict")).get("verdict"),
                }
            )
    return comparisons


def _filter_dropped_tom_count(run: dict[str, Any]) -> int | None:
    tom_filter = _dict(_dict(run.get("postprocess_filters")).get("tom_false_positive"))
    return _int_or_none(tom_filter.get("dropped_tom_count"))


def _tom_ratio(counts: dict[str, Any]) -> float | None:
    total = sum(int(value) for value in counts.values() if isinstance(value, int))
    if total <= 0:
        return None
    return round(int(counts.get("tom", 0)) / total, 4)


def _overall_status(runs: list[dict[str, Any]]) -> str:
    statuses = {str(run.get("status")) for run in runs}
    if not runs or statuses <= {"skipped"}:
        return "skipped"
    if statuses <= {"completed", "skipped"}:
        return "completed"
    if "completed" in statuses:
        return "completed_with_failures"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    return "unknown"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative_to_output(path: Path, output_dir: Path) -> str:
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return path.name


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in slug.split("-") if part) or "fixture"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
