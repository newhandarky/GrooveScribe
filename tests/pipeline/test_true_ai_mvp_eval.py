from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import scripts.run_true_ai_mvp_eval as mvp_eval
from scripts.run_true_ai_smoke_baseline import BaselineRunResult


def test_mvp_eval_report_runs_wav_and_generated_mp3_with_preset(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_process_runner(command, **_kwargs):
        Path(command[-1]).write_bytes(b"synthetic mp3")
        return _completed(command)

    def fake_run_baseline(config, **_kwargs):
        calls.append(
            (
                config.input_path.suffix,
                config.adtof_threshold_preset,
                config.adtof_class_thresholds,
                config.tom_filter_preset,
            )
        )
        report_path = tmp_path / config.run_id / "baseline.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(_baseline_payload(config.run_id)), encoding="utf-8")
        return BaselineRunResult("completed", report_path, 0)

    monkeypatch.setattr(mvp_eval, "run_baseline", fake_run_baseline)

    report = mvp_eval.run_mvp_eval(
        mvp_eval.MvpEvalConfig(
            output_dir=tmp_path,
            wav_fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template="adtof --audio {input} --out {output}",
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
            threshold_preset="separated_v1",
        ),
        process_runner=fake_process_runner,
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert calls == [(".wav", "separated_v1", None, None), (".mp3", "separated_v1", None, None)]
    assert report["status"] == "completed"
    assert report["threshold_preset"] == "separated_v1"
    assert report["class_thresholds"]["tom"] == 0.18
    assert report["summary"]["candidate_count"] == 2
    assert report["summary"]["best_usability_score"] == 4
    assert {fixture["input_format"] for fixture in report["fixtures"]} == {"wav", "mp3"}
    assert all(fixture["musicxml"] == {"available": True, "parseable": True, "warnings": []} for fixture in report["fixtures"])
    assert all(fixture["candidate_gate"]["status"] == "passed" for fixture in report["fixtures"])
    assert all(fixture["variant"] == "filter_off" for fixture in report["fixtures"])
    report_text = json.dumps(report, ensure_ascii=False)
    assert "/tmp/" not in report_text
    assert "/Users/" not in report_text
    assert "command_template" not in report_text
    assert report["redaction"]["status"] == "passed"


def test_mvp_eval_compare_mode_runs_filter_off_and_tom_guard(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_process_runner(command, **_kwargs):
        Path(command[-1]).write_bytes(b"synthetic mp3")
        return _completed(command)

    def fake_run_baseline(config, **_kwargs):
        calls.append((config.input_path.suffix, config.run_id, config.tom_filter_preset))
        report_path = tmp_path / config.run_id / "baseline.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        filtered = config.tom_filter_preset == "tom_guard_v1"
        quality = {
            "raw_event_count": 18,
            "processed_event_count": 16 if filtered else 18,
            "raw_note_histogram": {"35": 3, "38": 4, "42": 5, "47": 6},
            "processed_drum_counts": {"kick": 3, "snare": 4, "closed_hat": 5, "tom": 4 if filtered else 6},
            "quality_flags": [],
            "postprocess_filters": {
                "tom_false_positive": {
                    "enabled": filtered,
                    "preset": "tom_guard_v1" if filtered else None,
                    "status": "applied" if filtered else "disabled",
                    "input_tom_count": 6,
                    "output_tom_count": 4 if filtered else 6,
                    "dropped_tom_count": 2 if filtered else 0,
                    "target_max_tom_ratio": 0.3,
                }
            },
        }
        report_path.write_text(json.dumps(_baseline_payload(config.run_id, quality=quality)), encoding="utf-8")
        return BaselineRunResult("completed", report_path, 0)

    monkeypatch.setattr(mvp_eval, "run_baseline", fake_run_baseline)

    report = mvp_eval.run_mvp_eval(
        mvp_eval.MvpEvalConfig(
            output_dir=tmp_path,
            wav_fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template="adtof --audio {input} --out {output}",
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
            threshold_preset="separated_v1",
            tom_filter_preset="tom_guard_v1",
            compare_tom_filter=True,
        ),
        process_runner=fake_process_runner,
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert [call[2] for call in calls] == [None, "tom_guard_v1", None, "tom_guard_v1"]
    assert {fixture["variant"] for fixture in report["fixtures"]} == {"filter_off", "tom_guard_v1"}
    assert report["summary"]["filter_comparison"] == [
        {
            "fixture": "generated:synthetic_separated_kick_snare_hat_pattern.mp3",
            "input_format": "mp3",
            "filter_variant": "tom_guard_v1",
            "baseline_tom_count": 6,
            "filtered_tom_count": 4,
            "baseline_to_filtered_tom_delta": 2,
            "filter_report_dropped_tom_count": 2,
            "baseline_usability_score": 3,
            "filtered_usability_score": 4,
            "filtered_verdict": "mvp_candidate",
        },
        {
            "fixture": "tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav",
            "input_format": "wav",
            "filter_variant": "tom_guard_v1",
            "baseline_tom_count": 6,
            "filtered_tom_count": 4,
            "baseline_to_filtered_tom_delta": 2,
            "filter_report_dropped_tom_count": 2,
            "baseline_usability_score": 3,
            "filtered_usability_score": 4,
            "filtered_verdict": "mvp_candidate",
        },
    ]
    filtered_candidates = [item for item in report["summary"]["candidate_outputs"] if item["variant"] == "tom_guard_v1"]
    assert filtered_candidates
    assert all(item["postprocess_filters"]["tom_false_positive"]["status"] == "applied" for item in filtered_candidates)


def test_mvp_eval_candidate_gate_rejects_no_snare_and_unparseable_musicxml(tmp_path, monkeypatch) -> None:
    run_index = {"value": 0}

    def fake_process_runner(command, **_kwargs):
        Path(command[-1]).write_bytes(b"synthetic mp3")
        return _completed(command)

    def fake_run_baseline(config, **_kwargs):
        run_index["value"] += 1
        quality = {
            "raw_event_count": 9,
            "processed_event_count": 9,
            "raw_note_histogram": {"35": 3, "42": 4, "47": 2},
            "processed_drum_counts": {"kick": 3, "closed_hat": 4, "tom": 2},
            "quality_flags": ["no_snare_detected"],
        }
        validation = {"musicxml": {"available": True, "parseable": run_index["value"] == 1, "warnings": []}}
        report_path = tmp_path / config.run_id / "baseline.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(_baseline_payload(config.run_id, quality=quality, validation=validation)), encoding="utf-8")
        return BaselineRunResult("completed", report_path, 0)

    monkeypatch.setattr(mvp_eval, "run_baseline", fake_run_baseline)

    report = mvp_eval.run_mvp_eval(
        mvp_eval.MvpEvalConfig(
            output_dir=tmp_path,
            wav_fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template="adtof --audio {input} --out {output}",
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
            threshold_preset="separated_v1",
        ),
        process_runner=fake_process_runner,
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert report["summary"]["candidate_count"] == 0
    assert all(fixture["candidate_gate"]["status"] == "failed" for fixture in report["fixtures"])
    assert all("no_snare_detected" in fixture["blocking_quality_flags"] for fixture in report["fixtures"])


def _baseline_payload(
    run_id: str,
    *,
    quality: dict | None = None,
    validation: dict | None = None,
) -> dict:
    return {
        "status": "completed",
        "baseline_ref": f"baseline:{run_id}",
        "artifacts": {
            "raw_midi": {"path": "midi/raw_drum.mid", "available": True},
            "processed_midi": {"path": "midi/processed_drum.mid", "available": True},
            "drum_events": {"path": "midi/drum_events.json", "available": True},
            "musicxml": {"path": "notation/score.musicxml", "available": True},
            "pipeline_log": {"path": "logs/pipeline.json", "available": True},
        },
        "quality": quality
        or {
            "raw_event_count": 20,
            "processed_event_count": 20,
            "raw_note_histogram": {"35": 3, "38": 6, "42": 5, "47": 6},
            "processed_drum_counts": {"kick": 3, "snare": 6, "closed_hat": 5, "tom": 6},
            "quality_flags": [],
        },
        "validation": validation or {"musicxml": {"available": True, "parseable": True, "warnings": []}},
    }


def _completed(command):
    return mvp_eval.subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")
