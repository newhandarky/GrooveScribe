from __future__ import annotations

from ai_pipeline.notation.gate_calibration import apply_gate_calibration, calibrate_gate


def test_calibration_fails_closed_when_auto_ready_is_false_positive() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.42, False, True),
            _run("full_mix", 0.91, True, False),
        ]
    )

    assert calibration["status"] == "failed_closed"
    assert calibration["false_positive_count"] == 1
    gate = apply_gate_calibration(_gate(), calibration)
    assert gate["verdict"] == "playable_but_low_confidence"
    assert gate["delivery_allowed"] is False


def test_calibration_enables_ready_only_with_two_input_types_and_clean_evidence() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, True, True),
            _run("full_mix", 0.9, True, True),
        ]
    )

    assert calibration["status"] == "calibrated"
    gate = apply_gate_calibration(_gate(), calibration)
    assert gate["verdict"] == "performance_ready"
    assert gate["delivery_allowed"] is True


def _run(input_type: str, alignment: float, passed: bool, auto_candidate: bool) -> dict:
    return {
        "id": input_type,
        "input_type": input_type,
        "ground_truth_eval": {"status": "measured", "f1": 0.9},
        "ground_truth_passed": passed,
        "auto_gate_candidate": auto_candidate,
        "performance_gate": {"audio_alignment": {"onset_alignment_rate": alignment}},
    }


def _gate() -> dict:
    return {
        "verdict": "performance_ready",
        "delivery_allowed": True,
        "blocking_issues": ["gate_calibration_unavailable"],
        "audio_alignment": {"onset_alignment_rate": 0.95},
    }
