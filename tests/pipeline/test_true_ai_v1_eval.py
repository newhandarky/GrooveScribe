from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import run_true_ai_v1_eval
from scripts.run_true_ai_v1_eval import V1EvalConfig, run_v1_eval


def test_v1_eval_builds_human_correctable_readiness_report(tmp_path, monkeypatch) -> None:
    def fake_mvp_eval(config, *, process_runner, checked_at):
        return {
            "status": "completed",
            "fixtures": [
                {
                    "fixture": "synthetic_wav",
                    "input_format": "wav",
                    "variant": "tom_guard_v1",
                    "status": "completed",
                    "baseline_ref": "artifacts:synthetic_wav",
                    "baseline_report": "baseline.json",
                    "candidate_gate": {"status": "passed"},
                    "musicxml": {"available": True, "parseable": True},
                    "quality_verdict": {
                        "verdict": "mvp_candidate",
                        "usability_score": 4,
                        "limitations": [],
                    },
                    "processed_drum_counts": {"kick": 4, "snare": 4, "closed_hat": 8, "tom": 2},
                    "postprocess_filters": {
                        "tom_false_positive": {"enabled": True, "preset": "tom_guard_v1", "status": "applied"}
                    },
                },
                {
                    "fixture": "external:authorized_real_drum",
                    "input_format": "wav",
                    "variant": "tom_guard_v1",
                    "status": "completed",
                    "baseline_ref": "artifacts:external_real",
                    "baseline_report": "baseline.json",
                    "candidate_gate": {"status": "passed"},
                    "musicxml": {"available": True, "parseable": True},
                    "quality_verdict": {
                        "verdict": "draft_candidate_needs_review",
                        "usability_score": 3,
                        "limitations": ["tom_false_positive_likely"],
                    },
                    "processed_drum_counts": {"kick": 5, "snare": 5, "closed_hat": 4, "tom": 6},
                    "postprocess_filters": {
                        "tom_false_positive": {
                            "enabled": True,
                            "preset": "tom_guard_v1",
                            "status": "no_safe_tom_filter_change",
                        }
                    },
                },
            ],
        }

    monkeypatch.setattr(run_true_ai_v1_eval, "run_mvp_eval", fake_mvp_eval)

    report = run_v1_eval(
        V1EvalConfig(
            output_dir=tmp_path / "v1-eval",
            wav_fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template=None,
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
        ),
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert report["status"] == "completed"
    assert report["product_preset"] == {
        "threshold_preset": "separated_v1",
        "tom_filter_preset": "tom_guard_v1",
    }
    assert report["v1_readiness"] == {
        "repo_fixture_human_correctable": True,
        "external_fixture_count": 1,
        "external_human_correctable_count": 0,
        "v1_complete": False,
    }
    assert report["fixtures"][0]["human_correctable"] is True
    assert report["fixtures"][1]["human_correctable"] is False
    assert report["fixtures"][1]["primary_blocker"] == "tom_false_positive_likely"
    assert report["fixtures"][0]["manual_eval_seed"] == {
        "artifact_ref": "artifacts:synthetic_wav",
        "baseline_report_ref": "baseline.json",
        "human_correctable": "",
        "primary_blocker": "",
        "review_notes_ref": "",
    }
    assert report["redaction"] == {"status": "passed", "unsafe_token_count": 0}
    written = json.loads((tmp_path / "v1-eval" / "v1_eval_report.json").read_text(encoding="utf-8"))
    assert written["v1_readiness"] == report["v1_readiness"]
    assert_public_safe(report)


def assert_public_safe(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for token in ("/Users/", "/tmp/", "command_template", "Traceback", "stdout", "stderr"):
        assert token not in text
