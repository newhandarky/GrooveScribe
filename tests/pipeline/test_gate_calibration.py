from __future__ import annotations

import math

from ai_pipeline.notation.gate_calibration import apply_gate_calibration, calibrate_gate


def test_calibration_fails_closed_when_auto_ready_is_false_positive() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.92, False, True),
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
            _run("full_mix", 0.88, True, True, real_audio=True),
            _run("full_mix", 0.9, True, True, real_audio=True),
        ]
    )

    assert calibration["status"] == "calibrated"
    gate = apply_gate_calibration(_gate(), calibration)
    assert gate["verdict"] == "performance_ready"
    assert gate["delivery_allowed"] is True


def test_calibration_restores_original_ready_verdict_after_initial_fail_closed_downgrade() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, True, True, real_audio=True),
            _run("full_mix", 0.9, True, True, real_audio=True),
        ]
    )
    initially_downgraded = {
        **_gate(),
        "verdict": "playable_but_low_confidence",
        "delivery_allowed": False,
        "blocking_issues": ["gate_calibration_unavailable"],
        "uncalibrated_verdict": "performance_ready",
    }

    gate = apply_gate_calibration(initially_downgraded, calibration)

    assert gate["verdict"] == "performance_ready"
    assert gate["delivery_allowed"] is True
    assert gate["blocking_issues"] == []


def test_calibration_reconsiders_only_provisional_alignment_failure() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.6458, True, True, real_audio=True),
            _run("full_mix", 0.9, True, True, real_audio=True),
        ]
    )
    provisional = {
        "verdict": "needs_better_source",
        "delivery_allowed": False,
        "blocking_issues": ["audio_onset_alignment_low", "gate_calibration_unavailable"],
        "audio_alignment": {"onset_alignment_rate": 0.6458},
        "uncalibrated_verdict": "needs_better_source",
    }

    gate = apply_gate_calibration(provisional, calibration)

    assert calibration["min_auto_onset_alignment"] == 0.645
    assert gate["verdict"] == "performance_ready"
    assert gate["delivery_allowed"] is True
    assert gate["blocking_issues"] == []


def test_calibration_requires_accepted_drum_only_and_full_mix_evidence() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, False, False),
            _run("full_mix", 0.9, False, False),
        ]
    )

    assert calibration["status"] == "insufficient_evidence"
    assert calibration["accepted_input_types"] == ["drum_only"]
    gate = apply_gate_calibration(_gate(), calibration)
    assert gate["verdict"] == "playable_but_low_confidence"
    assert gate["delivery_allowed"] is False


def test_synthetic_full_mix_cannot_enable_performance_ready_calibration() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, True, True, real_audio=False),
            _run("full_mix", 0.90, True, True, real_audio=False),
        ]
    )

    assert calibration["status"] == "insufficient_evidence"
    assert calibration["allow_performance_ready"] is False
    assert calibration["accepted_real_audio_reference_count"] == 0
    assert calibration["accepted_real_audio_input_types"] == []


def test_ineligible_full_mix_cannot_complete_calibration_coverage() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, True, True, eligible=False),
            _run("drum_only", 0.90, True, True),
        ]
    )

    assert calibration["status"] == "insufficient_evidence"
    assert calibration["accepted_input_types"] == ["drum_only"]


def test_ineligible_low_alignment_cannot_lower_calibrated_threshold() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.95, True, True),
            _run("full_mix", 0.88, True, True, real_audio=True),
            _run("full_mix", 0.90, True, True, real_audio=True),
            _run("full_mix", 0.10, True, True, eligible=False),
        ]
    )

    assert calibration["status"] == "calibrated"
    assert calibration["min_auto_onset_alignment"] == 0.88


def test_calibration_fails_closed_for_false_positive_enabled_only_by_candidate_threshold() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.72, True, True),
            _run("full_mix", 0.65, True, True, real_audio=True),
            _run("full_mix", 0.67, True, True, real_audio=True),
            _run("drum_only", 0.66, False, False, issues=["audio_onset_alignment_low"]),
        ]
    )

    assert calibration["status"] == "failed_closed"
    assert calibration["false_positive_count"] == 1
    assert calibration["false_positive_ids"] == ["drum_only"]


def test_structural_issue_is_not_a_calibrated_ready_candidate() -> None:
    calibration = calibrate_gate(
        [
            _run("drum_only", 0.72, True, True),
            _run("full_mix", 0.65, True, True, real_audio=True),
            _run("full_mix", 0.67, True, True, real_audio=True),
            _run("drum_only", 0.66, False, False, issues=["audio_onset_alignment_low", "tom_outside_fill"]),
        ]
    )

    assert calibration["status"] == "calibrated"
    assert calibration["false_positive_count"] == 0


def test_invalid_calibration_thresholds_fail_closed() -> None:
    for threshold in (-1.0, 1.01, math.nan, math.inf, True):
        gate = apply_gate_calibration(
            _gate(),
            {
                "status": "calibrated",
                "allow_performance_ready": True,
                "min_auto_onset_alignment": threshold,
                "accepted_real_audio_reference_count": 1,
                "accepted_real_audio_input_types": ["full_mix"],
            },
        )

        assert gate["delivery_allowed"] is False
        assert "calibrated_onset_threshold_not_met" in gate["blocking_issues"]


def test_invalid_full_mix_alignment_cannot_complete_accepted_coverage() -> None:
    for invalid_alignment in (-1.0, 1.01, math.nan, math.inf, True):
        calibration = calibrate_gate(
            [
                _run("drum_only", 0.90, True, True),
                _run("drum_only", 0.92, True, True),
                _run("full_mix", invalid_alignment, True, True),
            ]
        )

        assert calibration["status"] == "insufficient_evidence"
        assert calibration["accepted_input_types"] == ["drum_only"]
        assert calibration["accepted_reference_count"] == 2


def test_invalid_full_mix_alignment_cannot_change_existing_calibration_threshold() -> None:
    baseline = [
        _run("drum_only", 0.90, True, True),
        _run("full_mix", 0.80, True, True, real_audio=True),
        _run("full_mix", 0.85, True, True, real_audio=True),
    ]
    expected = calibrate_gate(baseline)

    for invalid_alignment in (-1.0, 1.01, math.nan, math.inf, True):
        calibration = calibrate_gate(
            [
                *baseline,
                _run("full_mix", invalid_alignment, True, True),
            ]
        )

        assert calibration["status"] == "calibrated"
        assert calibration["min_auto_onset_alignment"] == expected["min_auto_onset_alignment"]
        assert calibration["accepted_reference_count"] == expected["accepted_reference_count"]
        assert calibration["accepted_input_types"] == expected["accepted_input_types"]


def _run(
    input_type: str,
    alignment: object,
    passed: bool,
    auto_candidate: bool,
    *,
    eligible: bool = True,
    issues: list[str] | None = None,
    real_audio: bool = False,
) -> dict:
    return {
        "id": input_type,
        "input_type": input_type,
        "ground_truth_eval": {"status": "measured", "f1": 0.9},
        "ground_truth_passed": passed,
        "auto_gate_candidate": auto_candidate,
        "calibration_eligible": eligible,
        "real_audio_verified": real_audio,
        "performance_gate": {
            "audio_alignment": {"onset_alignment_rate": alignment},
            "blocking_issues": issues or [],
        },
    }


def _gate() -> dict:
    return {
        "verdict": "performance_ready",
        "delivery_allowed": True,
        "blocking_issues": ["gate_calibration_unavailable"],
        "audio_alignment": {"onset_alignment_rate": 0.95},
    }
