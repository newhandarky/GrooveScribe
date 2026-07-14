from __future__ import annotations

from statistics import quantiles
from typing import Iterable


def calibrate_gate(benchmark_runs: Iterable[dict]) -> dict[str, object]:
    """Calibrate the auto-onset threshold from authorized MIDI references.

    A calibration is valid only when it contains drum-only and full-mix evidence
    and none of the auto-ready candidates violates its manifest acceptance policy.
    """

    measured = [run for run in benchmark_runs if (run.get("ground_truth_eval") or {}).get("status") == "measured"]
    input_types = {str(run.get("input_type")) for run in measured}
    false_positives = [run for run in measured if run.get("auto_gate_candidate") and not run.get("ground_truth_passed")]
    accepted = [run for run in measured if run.get("ground_truth_passed")]
    alignment_values = [float((run.get("performance_gate") or {}).get("audio_alignment", {}).get("onset_alignment_rate")) for run in accepted if isinstance((run.get("performance_gate") or {}).get("audio_alignment", {}).get("onset_alignment_rate"), (int, float))]
    enough_coverage = len(measured) >= 3 and {"drum_only", "full_mix"}.issubset(input_types)
    if false_positives:
        status = "failed_closed"
    elif enough_coverage and alignment_values:
        status = "calibrated"
    else:
        status = "insufficient_evidence"
    threshold = min(alignment_values) if alignment_values else None
    return {
        "schema_version": "1.0",
        "status": status,
        "benchmark_item_count": len(measured),
        "input_types": sorted(input_types),
        "false_positive_count": len(false_positives),
        "false_positive_ids": [str(run.get("id")) for run in false_positives],
        "accepted_reference_count": len(accepted),
        "min_auto_onset_alignment": round(threshold, 3) if threshold is not None else None,
        "alignment_distribution": _distribution(alignment_values),
        "allow_performance_ready": status == "calibrated",
    }


def apply_gate_calibration(gate: dict, calibration: dict | None) -> dict:
    result = {**gate, "ground_truth_verified": False}
    issues = [issue for issue in (result.get("blocking_issues") or []) if issue not in {"gate_calibration_unavailable", "gate_calibration_not_ready", "calibrated_onset_threshold_not_met"}]
    if calibration is None:
        return _downgrade(result, issues, "gate_calibration_unavailable")
    if calibration.get("status") != "calibrated" or not calibration.get("allow_performance_ready"):
        return _downgrade(result, issues, "gate_calibration_not_ready")
    threshold = calibration.get("min_auto_onset_alignment")
    alignment = (result.get("audio_alignment") or {}).get("onset_alignment_rate")
    if not isinstance(threshold, (int, float)) or not isinstance(alignment, (int, float)) or alignment < threshold:
        return _downgrade(result, issues, "calibrated_onset_threshold_not_met")
    result["calibration_status"] = "applied"
    return result


def _downgrade(result: dict, issues: list[str], issue: str) -> dict:
    if result.get("verdict") == "performance_ready":
        result["verdict"] = "playable_but_low_confidence"
        result["delivery_allowed"] = False
    result["blocking_issues"] = sorted(set([*issues, issue]))
    result["calibration_status"] = "not_applied"
    return result


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "p25": None}
    ordered = sorted(values)
    p25 = quantiles(ordered, n=4, method="inclusive")[0] if len(ordered) > 1 else ordered[0]
    return {"min": round(ordered[0], 3), "median": round(ordered[len(ordered) // 2], 3), "p25": round(p25, 3)}
