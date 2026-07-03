import csv
import json
from pathlib import Path

from scripts.generate_manual_eval_row import FIELDNAMES, generate_manual_eval_row


def test_manual_eval_row_generator_matches_template_and_redacts_completed_baseline(tmp_path: Path) -> None:
    template_fields = next(csv.reader(Path("tests/manual_eval/manual_eval_template.csv").open(encoding="utf-8")))
    baseline_path = tmp_path / "baseline-run-1" / "baseline.json"
    baseline = {
        "status": "completed",
        "baseline_ref": "baseline:explicit-run",
        "checked_at": "2026-07-03T00:00:00Z",
        "input_fixture": "/Users/dev/private/audio.wav",
        "output_dir_name": "20260703-true-ai",
        "runtime": {
            "python_version": "3.11.15",
            "demucs_device": "cpu",
            "adtof_device": "cpu",
            "adtof_threshold": "0.5",
        },
        "quality": {
            "raw_event_count": 7,
            "processed_event_count": 5,
            "raw_note_histogram": {"35": 2, "47": 5},
            "processed_drum_counts": {"kick": 2, "tom": 3},
            "quality_flags": ["hihat_missing_likely"],
            "warnings": [
                "hihat_missing_likely",
                "command_failed",
                "/tmp/private/path",
                "stderr leaked",
                "Traceback leaked",
                "command_template leaked",
            ],
        },
        "exports": {"pdf": {"status": "unavailable", "optional": True}},
    }

    row = generate_manual_eval_row(
        baseline,
        baseline_report_path=baseline_path,
        reviewer="QA",
        runtime_mode="true_ai",
        pipeline_version="local-first-v1",
    )

    assert FIELDNAMES == template_fields
    assert list(row.keys()) == FIELDNAMES
    assert row["date"] == "2026-07-03"
    assert row["fixture_name"] == "<local-path>"
    assert row["baseline_report_ref"] == "baseline:explicit-run"
    assert row["artifact_ref"] == "external:20260703-true-ai"
    assert row["raw_event_count"] == "7"
    assert json.loads(row["processed_drum_counts"]) == {"kick": 2, "tom": 3}
    assert row["quality_flags"] == "hihat_missing_likely"
    assert row["warnings"] == "hihat_missing_likely; command_failed"
    assert "/Users/" not in str(row)
    assert "/tmp/" not in str(row)
    assert "stderr" not in str(row)
    assert "Traceback" not in str(row)
    assert "command_template" not in str(row)


def test_manual_eval_row_generator_keeps_blocked_scores_blank_and_reason_required(tmp_path: Path) -> None:
    baseline_path = tmp_path / "blocked-run" / "baseline.json"
    baseline = {
        "status": "blocked",
        "checked_at": "2026-07-03T00:00:00Z",
        "input_fixture": "synthetic_clean_drum_pattern.wav",
        "blocked_reason": "ADTOF verify input missing at /private/tmp/input.wav",
        "runtime": {"python_version": "3.11.15", "adtof_device": "cpu", "adtof_threshold": "0.5"},
        "preflight": {"adtof_status_code": "verify_input_missing"},
    }

    row = generate_manual_eval_row(
        baseline,
        baseline_report_path=baseline_path,
        reviewer="QA",
        runtime_mode="true_ai",
        pipeline_version="local-first-v1",
    )

    assert row["blocked_reason"] == "ADTOF verify input missing at <local-path>"
    assert row["kick_score"] == ""
    assert row["overall_usability_score"] == ""
    assert "Baseline blocked" in row["notes"]
    assert "/private/tmp/" not in str(row)

    fallback_row = generate_manual_eval_row(
        {**baseline, "blocked_reason": ""},
        baseline_report_path=baseline_path,
        reviewer="QA",
        runtime_mode="true_ai",
        pipeline_version="local-first-v1",
    )
    assert fallback_row["blocked_reason"] == "ADTOF status_code=verify_input_missing"
