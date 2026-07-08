from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts import run_adtof_output_experiment as experiment


def test_mapping_verification_uses_general_midi_without_tom_remap() -> None:
    verification = experiment.mapping_verification({"35": 1, "42": 2, "47": 6})

    assert verification["mapping_source"] == "general_midi"
    assert verification["no_evidence_remap_applied"] is True
    assert verification["raw_snare_present"] is False
    assert verification["raw_hihat_present"] is True
    assert verification["raw_tom_count"] == 6
    note_47 = next(item for item in verification["notes"] if item["raw_note"] == 47)
    assert note_47 == {
        "raw_note": 47,
        "count": 6,
        "mapped_note": 45,
        "mapped_drum": "tom",
        "mapping_source": "general_midi",
    }


def test_adtof_output_experiment_report_marks_per_class_threshold_supported(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(experiment, "run_quality_matrix", lambda *_args, **_kwargs: _matrix_payload())

    report = experiment.run_adtof_output_experiment(
        _config(tmp_path),
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert report["status"] == "completed"
    assert report["per_class_threshold_supported"] is True
    assert report["per_class_threshold_order"] == ["kick", "snare", "tom", "closed_hat", "cymbal"]
    assert report["candidate_thresholds"] == []
    assert report["conclusion"]["best_usability_score"] == 2
    assert report["redaction"]["status"] == "passed"


def test_adtof_output_experiment_report_includes_histogram_counts_and_gate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(experiment, "run_quality_matrix", lambda *_args, **_kwargs: _matrix_payload())

    report = experiment.run_adtof_output_experiment(
        _config(tmp_path),
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    run = report["runs"][0]
    assert run["threshold"] == "0.1"
    assert run["threshold_mode"] == "scalar"
    assert run["class_thresholds"] is None
    assert run["raw_note_histogram"] == {"35": 1, "42": 2, "47": 6}
    assert run["processed_drum_counts"] == {"closed_hat": 2, "kick": 1, "tom": 6}
    assert run["musicxml"] == {"available": True, "parseable": True}
    assert run["candidate_gate"]["status"] == "failed"
    assert run["kick_count"] == 1
    assert run["snare_count"] == 0
    assert run["hihat_count"] == 2
    assert run["tom_count"] == 6
    assert run["usability_score"] == 2
    assert run["raw_mapping_verification"]["raw_snare_present"] is False
    assert report["conclusion"]["snare_seen_in_raw"] is False
    assert report["conclusion"]["snare_seen_in_processed"] is False
    assert (tmp_path / "adtof_output_experiment_report.json").exists()


def test_adtof_output_experiment_report_records_per_class_thresholds(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_quality_matrix(config, **_kwargs):
        calls.append(config.adtof_class_thresholds)
        return _matrix_payload()

    monkeypatch.setattr(experiment, "run_quality_matrix", fake_run_quality_matrix)

    report = experiment.run_adtof_output_experiment(
        experiment.AdtofOutputExperimentConfig(
            fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            output_dir=tmp_path,
            thresholds=("0.1",),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template=".venv-ai/bin/adtof --audio {input} --out {output}",
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
            per_class_configs=("A:kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08",),
        ),
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert calls == [None, "kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08"]
    assert report["runs"][1]["threshold"] == "A"
    assert report["runs"][1]["threshold_mode"] == "per_class"
    assert report["runs"][1]["scalar_threshold"] == "0.06"
    assert report["runs"][1]["class_thresholds"] == {
        "kick": 0.06,
        "snare": 0.04,
        "tom": 0.12,
        "closed_hat": 0.06,
        "cymbal": 0.08,
    }


def test_adtof_output_experiment_report_records_threshold_preset(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_quality_matrix(config, **_kwargs):
        calls.append(config.adtof_class_thresholds)
        return _matrix_payload()

    monkeypatch.setattr(experiment, "run_quality_matrix", fake_run_quality_matrix)

    report = experiment.run_adtof_output_experiment(
        experiment.AdtofOutputExperimentConfig(
            fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
            output_dir=tmp_path,
            thresholds=("0.1",),
            ai_python=".venv-ai/bin/python",
            demucs_device="cpu",
            adtof_command_template=".venv-ai/bin/adtof --audio {input} --out {output}",
            adtof_checkpoint=None,
            adtof_device="cpu",
            timeout_seconds=60,
            threshold_preset="separated_v1",
        ),
        checked_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    assert calls == [None, "0.06,0.04,0.18,0.06,0.08"]
    assert report["threshold_preset"] == "separated_v1"
    assert report["runs"][1]["threshold"] == "separated_v1"
    assert report["runs"][1]["class_thresholds"]["tom"] == 0.18


def _config(tmp_path: Path) -> experiment.AdtofOutputExperimentConfig:
    return experiment.AdtofOutputExperimentConfig(
        fixture=Path("tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav"),
        output_dir=tmp_path,
        thresholds=("0.1",),
        ai_python=".venv-ai/bin/python",
        demucs_device="cpu",
        adtof_command_template=".venv-ai/bin/adtof --audio {input} --out {output}",
        adtof_checkpoint=None,
        adtof_device="cpu",
        timeout_seconds=60,
    )


def _matrix_payload() -> dict:
    return {
        "status": "completed",
        "summary": {"candidate_thresholds": []},
        "fixtures": [
            {
                "fixture": "tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav",
                "status": "completed",
                "runs": [
                    {
                        "threshold": "0.1",
                        "status": "completed",
                        "raw_event_count": 9,
                        "processed_event_count": 9,
                        "raw_note_histogram": {"35": 1, "42": 2, "47": 6},
                        "processed_drum_counts": {"closed_hat": 2, "kick": 1, "tom": 6},
                        "quality_flags": ["no_snare_detected"],
                        "musicxml": {"available": True, "parseable": True},
                        "minimum_gate": {
                            "status": "failed",
                            "blocking_flags": ["no_snare_detected"],
                        },
                    }
                ],
            }
        ],
    }


def test_usability_score_reaches_three_for_candidate_with_core_drums() -> None:
    assert (
        experiment.usability_score(
            status="completed",
            processed_event_count=15,
            processed_drum_counts={"closed_hat": 4, "kick": 3, "snare": 1, "tom": 7},
            quality_flags=[],
            musicxml={"available": True, "parseable": True},
            candidate_gate={"status": "passed"},
        )
        == 3
    )


def test_usability_score_stays_low_when_candidate_gate_fails() -> None:
    assert (
        experiment.usability_score(
            status="completed",
            processed_event_count=12,
            processed_drum_counts={"closed_hat": 3, "kick": 2, "tom": 7},
            quality_flags=["no_snare_detected"],
            musicxml={"available": True, "parseable": True},
            candidate_gate={"status": "failed"},
        )
        == 2
    )
