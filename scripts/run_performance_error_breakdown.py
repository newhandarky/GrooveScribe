from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_pipeline.benchmark.metrics import (
    aggregate_by_input_type,
    audit_drum_midi_contract,
    primary_failure_stage,
)
from ai_pipeline.benchmark.provenance import UNSAFE_TOKENS, validate_item_provenance

_ROOT = Path(__file__).resolve().parents[1]
_UNSAFE = UNSAFE_TOKENS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Break down benchmark errors across raw, processed, and chart MIDI.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def run_breakdown(config: argparse.Namespace) -> dict[str, Any]:
    if any(_is_within_repo(path) for path in (config.manifest, config.benchmark_dir, config.output_dir)):
        return _write_blocked(config.output_dir, "benchmark_paths_must_be_outside_repo")
    manifest = _read(config.manifest)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = _item_breakdown(item, config.benchmark_dir)
        rows.append(row)
    report = {
        "schema_version": "1.0",
        "status": "completed" if rows else "skipped",
        "ground_truth_verified": any(row.get("status") == "measured" for row in rows),
        "real_audio_verified": any(row.get("real_audio_verified") is True for row in rows),
        "synthetic_full_mix_present": any(row.get("synthetic_full_mix") is True for row in rows),
        "items": rows,
        "by_input_type": aggregate_by_input_type(rows),
        "contract_audit": _contract_audit_summary(rows),
        "failure_ranking": _ranking(rows),
        "summary": {
            "run_count": len(rows),
            "measured_count": sum(row.get("status") == "measured" for row in rows),
            "skipped_count": sum(row.get("status") == "skipped" for row in rows),
        },
    }
    report = _public_report(report)
    _assert_safe(report)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "performance_error_breakdown.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _write_blocked(output_dir: Path, reason: str) -> dict[str, Any]:
    report = _public_report({"schema_version": "1.0", "status": "blocked", "summary": {"reason": reason}})
    if not _is_within_repo(output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "performance_error_breakdown.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _item_breakdown(item: dict[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = Path(str(item.get("audio_path") or ""))
    ground_truth = Path(str(item.get("ground_truth_midi_path") or ""))
    run = benchmark_dir / "runs" / item_id
    artifact_root = _canonical_candidate_root(run)
    paths = {
        "raw": artifact_root / "midi" / "raw_drum.mid",
        "processed": artifact_root / "midi" / "processed_drum.mid",
        "chart": artifact_root / "notation" / "performance_score.mid",
    }
    provenance_reason = validate_item_provenance(item, audio, ground_truth, repository_root=_ROOT)
    if provenance_reason is not None:
        return {
            "id": item_id,
            "status": "skipped",
            "reason": provenance_reason,
            "input_type": str(item.get("input_type") or "unknown"),
            "synthetic_full_mix": item.get("synthetic_full_mix") is True,
            "real_audio_verified": False,
            "stages": {},
            "primary_failure_stage": "unknown",
        }
    audits = {stage: audit_drum_midi_contract(path, ground_truth) for stage, path in paths.items()}
    stages = {stage: audit["uncorrected"] for stage, audit in audits.items()}
    corrected_stages = {stage: audit["offset_corrected"] for stage, audit in audits.items()}
    return {
        "id": item_id,
        "status": "measured" if ground_truth.exists() and all(path.exists() for path in paths.values()) else "skipped",
        "input_type": str(item.get("input_type") or "unknown"),
        "synthetic_full_mix": item.get("synthetic_full_mix") is True,
        "real_audio_verified": bool(item.get("ground_truth_verified") is True and item.get("synthetic_full_mix") is not True),
        "stages": stages,
        "contract_audit": {
            "taxonomy": "benchmark_6_class_v1",
            "stages": audits,
            "primary_failure_stage_after_offset_audit": primary_failure_stage(corrected_stages),
        },
        "primary_failure_stage": primary_failure_stage(stages),
    }


def _canonical_candidate_root(run: Path) -> Path:
    """Use selected multi-candidate artifacts while keeping paths out of reports."""

    pipeline = _read(run / "logs" / "pipeline.json")
    analysis = pipeline.get("candidate_analysis") if isinstance(pipeline.get("candidate_analysis"), dict) else {}
    candidate_id = analysis.get("canonical_candidate_id")
    candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    selected = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("candidate_id") == candidate_id
            and candidate.get("status") == "completed"
        ),
        None,
    )
    return run / "candidates" / _safe_id(candidate_id) if selected is not None and isinstance(candidate_id, str) else run


def _contract_audit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"taxonomy": "benchmark_6_class_v1", "by_input_type": {}}
    for input_type in sorted({str(row.get("input_type") or "unknown") for row in rows}):
        scoped = [row for row in rows if str(row.get("input_type") or "unknown") == input_type]
        stage_summary: dict[str, Any] = {}
        for stage in ("raw", "processed", "chart"):
            audits = [
                row.get("contract_audit", {}).get("stages", {}).get(stage, {})
                for row in scoped
                if isinstance(row.get("contract_audit"), dict)
            ]
            measured = [audit for audit in audits if isinstance(audit, dict) and audit.get("status") == "measured"]
            deltas = [
                float(audit.get("global_timing_offset", {}).get("f1_delta") or 0.0)
                for audit in measured
                if isinstance(audit.get("global_timing_offset"), dict)
            ]
            stage_summary[stage] = {
                "measured_count": len(measured),
                "mean_f1_delta_after_offset_audit": round(sum(deltas) / len(deltas), 4) if deltas else None,
                "material_timing_gain_count": sum(delta >= 0.08 for delta in deltas),
            }
        summary["by_input_type"][input_type] = stage_summary
    return summary


def _ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: _stage_f1(row, "chart"))
    return [
        {"id": row["id"], "input_type": row["input_type"], "chart_f1": _stage_f1(row, "chart"), "primary_failure_stage": row["primary_failure_stage"]}
        for row in ranked[:10]
    ]


def _stage_f1(row: dict[str, Any], stage: str) -> float:
    value = row.get("stages", {}).get(stage, {})
    return float(value.get("f1") or 0.0) if isinstance(value, dict) else 0.0


def _read(path: Path) -> dict[str, Any]:
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
    if any(token in serialized for token in _UNSAFE):
        raise RuntimeError("error_breakdown_redaction_failed")


_PUBLIC_DRUMS = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_PUBLIC_REASONS = {
    "benchmark_paths_must_be_outside_repo",
    "benchmark_artifact_must_be_outside_repo",
    "benchmark_artifact_missing",
    "benchmark_checksum_mismatch",
    "benchmark_provenance_invalid",
}


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": report.get("status") if report.get("status") in {"completed", "skipped", "blocked"} else "blocked",
        "ground_truth_verified": report.get("ground_truth_verified") is True,
        "real_audio_verified": report.get("real_audio_verified") is True,
        "synthetic_full_mix_present": report.get("synthetic_full_mix_present") is True,
        "items": [_public_item(row) for row in report.get("items", []) if isinstance(row, dict)],
        "by_input_type": _public_aggregate(report.get("by_input_type")),
        "contract_audit": _public_contract_audit(report.get("contract_audit")),
        "failure_ranking": [_public_ranking(row) for row in report.get("failure_ranking", []) if isinstance(row, dict)],
        "summary": _public_summary(report.get("summary")),
    }


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_id(row.get("id")),
        "status": row.get("status") if row.get("status") in {"measured", "skipped"} else "skipped",
        "reason": _public_reason(row.get("reason")) if row.get("status") != "measured" else None,
        "input_type": row.get("input_type") if row.get("input_type") in {"drum_only", "full_mix"} else "unknown",
        "synthetic_full_mix": row.get("synthetic_full_mix") is True,
        "real_audio_verified": row.get("real_audio_verified") is True,
        "stages": {stage: _public_metrics((row.get("stages") or {}).get(stage)) for stage in ("raw", "processed", "chart")},
        "primary_failure_stage": row.get("primary_failure_stage") if row.get("primary_failure_stage") in {"postprocessor", "chart_arranger", "timing_alignment", "demucs_or_raw_model", "unknown"} else "unknown",
        "contract_audit": _public_item_audit(row.get("contract_audit")),
    }


def _public_metrics(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    per_drum = source.get("per_drum") if isinstance(source.get("per_drum"), dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "f1": _number(source.get("f1"), 0, 1),
        "mean_timing_error_ticks": _number(source.get("mean_timing_error_ticks"), 0, None),
        "per_drum": {drum: {"f1": _number(values.get("f1"), 0, 1)} for drum in _PUBLIC_DRUMS if isinstance(values := per_drum.get(drum), dict)},
    }


def _public_item_audit(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    stages = source.get("stages") if isinstance(source.get("stages"), dict) else {}
    return {
        "taxonomy": "benchmark_6_class_v1",
        "stages": {
            stage: {
                "status": audit.get("status") if isinstance(audit, dict) and audit.get("status") in {"measured", "unavailable"} else "unavailable",
                "uncorrected": _public_metrics(audit.get("uncorrected") if isinstance(audit, dict) else None),
                "offset_corrected": _public_metrics(audit.get("offset_corrected") if isinstance(audit, dict) else None),
                "f1_delta": _number(((audit.get("global_timing_offset") or {}).get("f1_delta")) if isinstance(audit, dict) else None, -1, 1),
            }
            for stage in ("raw", "processed", "chart")
            if isinstance(audit := stages.get(stage), dict)
        },
        "primary_failure_stage_after_offset_audit": source.get("primary_failure_stage_after_offset_audit") if source.get("primary_failure_stage_after_offset_audit") in {"postprocessor", "chart_arranger", "timing_alignment", "demucs_or_raw_model", "unknown"} else "unknown",
    }


def _public_aggregate(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        input_type: {
            "item_count": int(result.get("item_count") or 0),
            "stage_f1": {stage: _number((result.get("stage_f1") or {}).get(stage), 0, 1) for stage in ("raw", "processed", "chart")},
            "primary_failure_stages": {stage: int(count) for stage, count in (result.get("primary_failure_stages") or {}).items() if stage in {"postprocessor", "chart_arranger", "timing_alignment", "demucs_or_raw_model", "unknown"} and isinstance(count, int) and count >= 0},
        }
        for input_type in ("drum_only", "full_mix")
        if isinstance(result := source.get(input_type), dict)
    }


def _public_contract_audit(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    by_type = source.get("by_input_type") if isinstance(source.get("by_input_type"), dict) else {}
    return {"taxonomy": "benchmark_6_class_v1", "by_input_type": {input_type: {stage: {"measured_count": int(summary.get("measured_count") or 0), "mean_f1_delta_after_offset_audit": _number(summary.get("mean_f1_delta_after_offset_audit"), -1, 1), "material_timing_gain_count": int(summary.get("material_timing_gain_count") or 0)} for stage in ("raw", "processed", "chart") if isinstance(summary := (result or {}).get(stage), dict)} for input_type in ("drum_only", "full_mix") if isinstance(result := by_type.get(input_type), dict)}}


def _public_ranking(value: dict[str, Any]) -> dict[str, Any]:
    return {"id": _safe_id(value.get("id")), "input_type": value.get("input_type") if value.get("input_type") in {"drum_only", "full_mix"} else "unknown", "chart_f1": _number(value.get("chart_f1"), 0, 1), "primary_failure_stage": value.get("primary_failure_stage") if value.get("primary_failure_stage") in {"postprocessor", "chart_arranger", "timing_alignment", "demucs_or_raw_model", "unknown"} else "unknown"}


def _public_summary(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result = {key: int(source.get(key) or 0) for key in ("run_count", "measured_count", "skipped_count")}
    if source.get("reason") in _PUBLIC_REASONS:
        result["reason"] = source["reason"]
    return result


def _public_reason(value: object) -> str:
    return value if value in _PUBLIC_REASONS else "benchmark_provenance_invalid"


def _number(value: object, minimum: float, maximum: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if number < minimum or (maximum is not None and number > maximum):
        return None
    return round(number, 4)


if __name__ == "__main__":
    report = run_breakdown(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "performance_error_breakdown.json"}, ensure_ascii=False))
