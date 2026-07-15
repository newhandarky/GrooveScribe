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
    _assert_safe(report)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "performance_error_breakdown.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _item_breakdown(item: dict[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = Path(str(item.get("audio_path") or ""))
    ground_truth = Path(str(item.get("ground_truth_midi_path") or ""))
    run = benchmark_dir / "runs" / item_id
    paths = {
        "raw": run / "midi" / "raw_drum.mid",
        "processed": run / "midi" / "processed_drum.mid",
        "chart": run / "notation" / "performance_score.mid",
    }
    provenance_reason = validate_item_provenance(item, audio, ground_truth)
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


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark")).strip("-")[:80]


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    if any(token in serialized for token in _UNSAFE):
        raise RuntimeError("error_breakdown_redaction_failed")


if __name__ == "__main__":
    report = run_breakdown(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "performance_error_breakdown.json"}, ensure_ascii=False))
