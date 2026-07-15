from __future__ import annotations

import math
from statistics import quantiles
from typing import Iterable


def calibrate_gate(benchmark_runs: Iterable[dict]) -> dict[str, object]:
    """Calibrate the auto-onset threshold from authorized MIDI references.

    A calibration is valid only when it contains drum-only evidence plus at
    least one real-audio full-mix reference. Synthetic full-mix regression data
    remains useful for model comparison, but cannot authorize product delivery.
    """

    measured = [
        run
        for run in benchmark_runs
        if (run.get("ground_truth_eval") or {}).get("status") == "measured" and run.get("calibration_eligible") is True
    ]
    input_types = {str(run.get("input_type")) for run in measured}
    # Calibration must only be derived from explicitly eligible, measured
    # evidence. Low-fidelity regression fixtures may still appear in a report,
    # but can never broaden readiness coverage or lower its threshold.
    accepted = [
        run
        for run in measured
        if run.get("ground_truth_passed")
        and is_valid_onset_alignment(
            (run.get("performance_gate") or {}).get("audio_alignment", {}).get("onset_alignment_rate")
        )
    ]
    accepted_input_types = {str(run.get("input_type")) for run in accepted}
    accepted_real_audio = [run for run in accepted if run.get("real_audio_verified") is True]
    accepted_real_audio_input_types = {str(run.get("input_type")) for run in accepted_real_audio}
    alignment_values = [
        float((run.get("performance_gate") or {}).get("audio_alignment", {}).get("onset_alignment_rate"))
        for run in accepted
    ]
    provisional_threshold = math.floor(min(alignment_values) * 1000) / 1000 if alignment_values else None
    false_positives = [
        run
        for run in measured
        if _simulated_calibrated_ready(run, provisional_threshold) and not run.get("ground_truth_passed")
    ]
    enough_coverage = (
        len(measured) >= 3
        and {"drum_only", "full_mix"}.issubset(input_types)
        and {"drum_only", "full_mix"}.issubset(accepted_input_types)
        and "full_mix" in accepted_real_audio_input_types
    )
    if false_positives:
        status = "failed_closed"
    elif enough_coverage and alignment_values:
        status = "calibrated"
    else:
        status = "insufficient_evidence"
    return {
        "schema_version": "1.0",
        "status": status,
        "benchmark_item_count": len(measured),
        "input_types": sorted(input_types),
        "accepted_input_types": sorted(accepted_input_types),
        "accepted_real_audio_reference_count": len(accepted_real_audio),
        "accepted_real_audio_input_types": sorted(accepted_real_audio_input_types),
        "false_positive_count": len(false_positives),
        "false_positive_ids": [str(run.get("id")) for run in false_positives],
        "accepted_reference_count": len(accepted),
        # Floor, rather than round, so a benchmark item that established the
        # threshold cannot be rejected because its measured value was rounded up.
        "min_auto_onset_alignment": provisional_threshold,
        "alignment_distribution": _distribution(alignment_values),
        "allow_performance_ready": status == "calibrated",
    }


def apply_gate_calibration(gate: dict, calibration: dict | None) -> dict:
    result = {**gate, "ground_truth_verified": False}
    issues = _non_calibration_issues(result.get("blocking_issues"))
    if calibration is None:
        return _downgrade(result, issues, "gate_calibration_unavailable")
    if not _is_authorized_product_calibration(calibration):
        return _downgrade(result, issues, "gate_calibration_not_ready")
    threshold = calibration.get("min_auto_onset_alignment")
    alignment = (result.get("audio_alignment") or {}).get("onset_alignment_rate")
    if not is_valid_onset_alignment(threshold) or not is_valid_onset_alignment(alignment) or alignment < threshold:
        return _downgrade(result, issues, "calibrated_onset_threshold_not_met")
    # Benchmark items are first rendered without calibration. Once an
    # authorized threshold is available, discard only the provisional default
    # alignment failure and recalculate delivery from the remaining issues.
    issues = [issue for issue in issues if issue != "audio_onset_alignment_low"]
    if not issues:
        result["verdict"] = "performance_ready"
        result["delivery_allowed"] = True
    result["blocking_issues"] = sorted(set(issues))
    result["calibration_status"] = "applied"
    return result


def _is_authorized_product_calibration(calibration: dict) -> bool:
    """Require explicit real full-mix evidence at the point of delivery.

    ``status=calibrated`` alone is not a public-delivery authorization. This
    protects production jobs from legacy or hand-authored calibration files
    that were derived from synthetic-only benchmark data.
    """

    if calibration.get("status") != "calibrated" or not calibration.get("allow_performance_ready"):
        return False
    count = calibration.get("accepted_real_audio_reference_count")
    input_types = calibration.get("accepted_real_audio_input_types")
    return isinstance(count, int) and not isinstance(count, bool) and count > 0 and isinstance(input_types, list) and "full_mix" in input_types


def _simulated_calibrated_ready(run: dict, threshold: float | None) -> bool:
    """Model the only change a valid calibration is allowed to make.

    Calibration may clear a provisional onset failure. It cannot clear chart,
    rhythm, or playability failures.
    """

    if not is_valid_onset_alignment(threshold):
        return False
    gate = run.get("performance_gate")
    if not isinstance(gate, dict):
        return False
    alignment = (gate.get("audio_alignment") or {}).get("onset_alignment_rate")
    if not is_valid_onset_alignment(alignment) or alignment < threshold:
        return False
    issues = [issue for issue in _non_calibration_issues(gate.get("blocking_issues")) if issue != "audio_onset_alignment_low"]
    return not issues


def _non_calibration_issues(value: object) -> list[str]:
    provisional = {
        "gate_calibration_unavailable",
        "gate_calibration_not_ready",
        "calibrated_onset_threshold_not_met",
    }
    return [issue for issue in value or [] if isinstance(issue, str) and issue not in provisional]


def is_valid_onset_alignment(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0


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
