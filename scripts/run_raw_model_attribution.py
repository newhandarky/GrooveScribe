from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ai_pipeline.benchmark.metrics import DRUMS, compare_drum_midi
from ai_pipeline.benchmark.provenance import UNSAFE_TOKENS, validate_item_provenance


_ROOT = Path(__file__).resolve().parents[1]
_STAGES = ("raw", "processed", "chart")
_CANDIDATE_FAILURES = {
    "drum_transcription": ("transcription", "candidate_transcription_failed"),
    "midi_post_processing": ("postprocess", "candidate_postprocess_failed"),
    "notation_generation": ("notation", "candidate_notation_failed"),
}
_PUBLIC_REASONS = {
    "benchmark_paths_must_be_outside_repo",
    "benchmark_provenance_invalid",
    "benchmark_artifact_must_be_outside_repo",
    "benchmark_checksum_mismatch",
    "benchmark_artifact_missing",
    "reference_drums_audio_unavailable",
    "holdout_insufficient",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attribute raw-model benchmark failures using existing external artifacts.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def run_attribution(config: argparse.Namespace) -> dict[str, Any]:
    if any(_is_within_repo(path) for path in (config.manifest, config.benchmark_dir, config.output_dir)):
        return _write_report(config.output_dir, _blocked_report("benchmark_paths_must_be_outside_repo"))
    manifest = _read_json(config.manifest)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    rows = [_item_attribution(item, config.benchmark_dir) for item in items if isinstance(item, dict)]
    report = {
        "schema_version": "1.0",
        "status": "completed" if rows else "skipped",
        "items": rows,
        "by_input_type": _aggregate_by_input_type(rows),
        "data_split": _data_split(rows),
        "separation_attribution": _separation_attribution(rows),
        "experiment_decision": _experiment_decision(rows),
        "summary": {
            "item_count": len(rows),
            "measured_item_count": sum(row.get("status") == "measured" for row in rows),
            "failed_candidate_count": sum(
                candidate.get("status") == "failed" for row in rows for candidate in row.get("candidates", [])
            ),
        },
    }
    public = _public_report(report)
    _assert_safe(public)
    return _write_report(config.output_dir, public)


def _item_attribution(item: dict[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = _path(item.get("audio_path"))
    ground_truth = _path(item.get("ground_truth_midi_path"))
    provenance_reason = validate_item_provenance(item, audio, ground_truth, repository_root=_ROOT)
    base = {
        "id": item_id,
        "input_type": item.get("input_type") if item.get("input_type") in {"drum_only", "full_mix"} else "unknown",
        "benchmark_split": item.get("benchmark_split") if item.get("benchmark_split") in {"development", "holdout"} else None,
        "reference_drums_audio_available": _reference_drums_audio_available(item),
    }
    if provenance_reason is not None or ground_truth is None:
        return {**base, "status": "skipped", "reason": provenance_reason or "benchmark_provenance_invalid", "candidates": []}
    pipeline = _read_json(benchmark_dir / "runs" / item_id / "logs" / "pipeline.json")
    analysis = pipeline.get("candidate_analysis") if isinstance(pipeline.get("candidate_analysis"), dict) else {}
    candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    rows = [_candidate_attribution(candidate, benchmark_dir / "runs" / item_id, ground_truth) for candidate in candidates if isinstance(candidate, dict)]
    return {**base, "status": "measured" if rows else "skipped", "reason": None if rows else "benchmark_artifact_missing", "candidates": rows}


def _candidate_attribution(candidate: dict[str, Any], run_dir: Path, ground_truth: Path) -> dict[str, Any]:
    candidate_id = _safe_id(candidate.get("candidate_id"))
    status = candidate.get("status") if candidate.get("status") in {"completed", "failed"} else "failed"
    failed_stage = candidate.get("failed_stage") if candidate.get("failed_stage") in _CANDIDATE_FAILURES else None
    category, default_reason = _CANDIDATE_FAILURES.get(failed_stage, ("artifact", "candidate_artifact_unavailable"))
    reason = candidate.get("failure_reason_code")
    if reason not in {"candidate_transcription_failed", "candidate_postprocess_failed", "candidate_notation_failed"}:
        reason = default_reason if status == "failed" else None
    root = run_dir / "candidates" / candidate_id
    paths = {
        "raw": root / "midi" / "raw_drum.mid",
        "processed": root / "midi" / "processed_drum.mid",
        "chart": root / "notation" / "performance_score.mid",
    }
    strategy, preset = _candidate_strategy_fields(candidate.get("config"))
    return {
        "candidate_id": candidate_id,
        "threshold": _threshold(candidate.get("config")),
        "strategy": strategy,
        "adtof_threshold_preset": preset,
        "status": status,
        "failed_stage": failed_stage,
        "failure_category": category if status == "failed" else None,
        "failure_reason_code": reason,
        "stages": {stage: compare_drum_midi(path, ground_truth) for stage, path in paths.items()},
    }


def _aggregate_by_input_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for input_type in ("drum_only", "full_mix"):
        scoped = [row for row in rows if row.get("input_type") == input_type]
        candidates = [candidate for row in scoped for candidate in row.get("candidates", []) if candidate.get("status") == "completed"]
        result[input_type] = {
            "item_count": len(scoped),
            "completed_candidate_count": len(candidates),
            "stages": {stage: _mean_metrics([candidate.get("stages", {}).get(stage) for candidate in candidates]) for stage in _STAGES},
            "failure_categories": _counts(
                candidate.get("failure_category") for row in scoped for candidate in row.get("candidates", [])
            ),
        }
    return result


def _data_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    development = sum(row.get("benchmark_split") == "development" for row in rows)
    holdout = sum(row.get("benchmark_split") == "holdout" for row in rows)
    return {
        "status": "ready" if development and holdout else "holdout_insufficient",
        "development_item_count": development,
        "holdout_item_count": holdout,
        "policy": "manifest_benchmark_split_v1",
    }


def _separation_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reference_count = sum(row.get("reference_drums_audio_available") is True for row in rows)
    if not reference_count:
        return {
            "status": "unavailable",
            "reason": "reference_drums_audio_unavailable",
            "reference_drums_item_count": 0,
            "snr": {"status": "unavailable"},
        }
    # This report is deliberately reuse-only. A separate controlled runner can
    # attach reference-drums ADTOF artifacts in a later run; no SNR is inferred.
    return {
        "status": "unavailable",
        "reason": "reference_drums_adtof_artifacts_unavailable",
        "reference_drums_item_count": reference_count,
        "snr": {"status": "unavailable"},
    }


def _experiment_decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [candidate for row in rows for candidate in row.get("candidates", []) if candidate.get("status") == "failed"]
    if failures and all(candidate.get("failure_category") in {"transcription", "artifact"} for candidate in failures):
        return {"status": "candidate_resilience_selected", "reason": "candidate_failure_contract_available"}
    return {"status": "not_selected", "reason": "reference_drums_audio_unavailable"}


def _mean_metrics(values: list[object]) -> dict[str, Any]:
    measured = [value for value in values if isinstance(value, dict) and value.get("status") == "measured"]
    return {
        "measured_count": len(measured),
        "f1": _mean([value.get("f1") for value in measured]),
        "precision": _mean([_macro(value, "precision") for value in measured]),
        "recall": _mean([_macro(value, "recall") for value in measured]),
        "mean_timing_error_ticks": _mean([value.get("mean_timing_error_ticks") for value in measured]),
    }


def _macro(value: dict[str, Any], field: str) -> float | None:
    per_drum = value.get("per_drum") if isinstance(value.get("per_drum"), dict) else {}
    return _mean([metrics.get(field) for metrics in per_drum.values() if isinstance(metrics, dict)])


def _mean(values: list[object]) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]
    return round(sum(numbers) / len(numbers), 4) if numbers else None


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        if value in {"runtime", "artifact", "transcription", "postprocess", "notation"}:
            result[value] = result.get(value, 0) + 1
    return result


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": report.get("status") if report.get("status") in {"completed", "skipped", "blocked"} else "blocked",
        "items": [_public_item(item) for item in report.get("items", []) if isinstance(item, dict)],
        "by_input_type": {key: _public_aggregate(value) for key, value in (report.get("by_input_type") or {}).items() if key in {"drum_only", "full_mix"}},
        "data_split": _public_data_split(report.get("data_split")),
        "separation_attribution": _public_separation(report.get("separation_attribution")),
        "experiment_decision": _public_experiment(report.get("experiment_decision")),
        "summary": {key: int((report.get("summary") or {}).get(key) or 0) for key in ("item_count", "measured_item_count", "failed_candidate_count")},
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_id(item.get("id")),
        "status": item.get("status") if item.get("status") in {"measured", "skipped"} else "skipped",
        "reason": item.get("reason") if item.get("reason") in _PUBLIC_REASONS else None,
        "input_type": item.get("input_type") if item.get("input_type") in {"drum_only", "full_mix"} else "unknown",
        "benchmark_split": item.get("benchmark_split") if item.get("benchmark_split") in {"development", "holdout"} else None,
        "reference_drums_audio_available": item.get("reference_drums_audio_available") is True,
        "candidates": [_public_candidate(candidate) for candidate in item.get("candidates", []) if isinstance(candidate, dict)],
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    strategy, preset = _candidate_strategy_fields(candidate)
    return {
        "candidate_id": _safe_id(candidate.get("candidate_id")),
        "threshold": candidate.get("threshold") if candidate.get("threshold") in {0.3, 0.4, 0.5, 0.6} else None,
        "strategy": strategy,
        "adtof_threshold_preset": preset,
        "status": candidate.get("status") if candidate.get("status") in {"completed", "failed"} else "failed",
        "failed_stage": candidate.get("failed_stage") if candidate.get("failed_stage") in _CANDIDATE_FAILURES else None,
        "failure_category": candidate.get("failure_category") if candidate.get("failure_category") in {"runtime", "artifact", "transcription", "postprocess", "notation"} else None,
        "failure_reason_code": candidate.get("failure_reason_code") if candidate.get("failure_reason_code") in {"candidate_transcription_failed", "candidate_postprocess_failed", "candidate_notation_failed", "candidate_artifact_unavailable"} else None,
        "stages": {stage: _public_metrics((candidate.get("stages") or {}).get(stage)) for stage in _STAGES},
    }


def _candidate_strategy_fields(config: object) -> tuple[str, str | None]:
    source = config if isinstance(config, dict) else {}
    if source.get("strategy") == "scalar_threshold_v1" or source.get("threshold_strategy") == "scalar_candidate":
        return "scalar_threshold_v1", None
    if source.get("strategy") == "adtof_preset_v1" and source.get("adtof_threshold_preset") == "separated_v1":
        return "adtof_preset_v1", "separated_v1"
    return "unknown", None


def _public_metrics(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    per_drum = source.get("per_drum") if isinstance(source.get("per_drum"), dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "f1": _number(source.get("f1"), 0, 1),
        "mean_timing_error_ticks": _number(source.get("mean_timing_error_ticks"), 0, None),
        "per_drum": {
            drum: {field: _number(metrics.get(field), 0, 1) for field in ("precision", "recall", "f1")}
            for drum in DRUMS
            if isinstance(metrics := per_drum.get(drum), dict)
        },
    }


def _public_aggregate(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "item_count": int(source.get("item_count") or 0),
        "completed_candidate_count": int(source.get("completed_candidate_count") or 0),
        "stages": {stage: {key: _number(metrics.get(key), 0, None) if key != "measured_count" else int(metrics.get(key) or 0) for key in ("measured_count", "f1", "precision", "recall", "mean_timing_error_ticks")} for stage in _STAGES if isinstance(metrics := (source.get("stages") or {}).get(stage), dict)},
        "failure_categories": {
            category: int(count)
            for category, count in (source.get("failure_categories") or {}).items()
            if category in {"runtime", "artifact", "transcription", "postprocess", "notation"}
            and isinstance(count, int)
            and count >= 0
        },
    }


def _public_data_split(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {"status": source.get("status") if source.get("status") in {"ready", "holdout_insufficient"} else "holdout_insufficient", "development_item_count": int(source.get("development_item_count") or 0), "holdout_item_count": int(source.get("holdout_item_count") or 0), "policy": "manifest_benchmark_split_v1"}


def _public_separation(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {"status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable", "reason": source.get("reason") if source.get("reason") in {"reference_drums_audio_unavailable", "reference_drums_adtof_artifacts_unavailable"} else "reference_drums_audio_unavailable", "reference_drums_item_count": int(source.get("reference_drums_item_count") or 0), "snr": {"status": "unavailable"}}


def _public_experiment(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {"status": source.get("status") if source.get("status") in {"candidate_resilience_selected", "not_selected"} else "not_selected", "reason": source.get("reason") if source.get("reason") in {"candidate_failure_contract_available", "reference_drums_audio_unavailable"} else "reference_drums_audio_unavailable"}


def _blocked_report(reason: str) -> dict[str, Any]:
    return _public_report({"schema_version": "1.0", "status": "blocked", "summary": {}, "data_split": {}, "separation_attribution": {}, "experiment_decision": {"reason": reason}})


def _write_report(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    if not _is_within_repo(output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "raw_model_attribution.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _reference_drums_audio_available(item: dict[str, Any]) -> bool:
    path = _path(item.get("reference_drums_audio_path"))
    return path is not None and path.is_file() and not _is_within_repo(path)


def _path(value: object) -> Path | None:
    return Path(str(value)).expanduser() if isinstance(value, str) and value else None


def _threshold(value: object) -> float | None:
    config = value if isinstance(value, dict) else {}
    threshold = config.get("threshold")
    return round(float(threshold), 1) if isinstance(threshold, (int, float)) and float(threshold) in {0.3, 0.4, 0.5, 0.6} else None


def _number(value: object, minimum: float, maximum: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    result = float(value)
    return round(result, 4) if result >= minimum and (maximum is None or result <= maximum) else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_within_repo(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == _ROOT or _ROOT in resolved.parents


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark")).strip("-")[:80]


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    if any(token.lower() in serialized for token in UNSAFE_TOKENS):
        raise RuntimeError("raw_model_attribution_redaction_failed")


if __name__ == "__main__":
    report = run_attribution(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "raw_model_attribution.json"}, ensure_ascii=False))
