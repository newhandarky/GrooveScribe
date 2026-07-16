from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import run_v1_real_audio_pilot
from scripts.run_v1_real_audio_pilot import main as real_audio_pilot_main
from scripts.check_v1_true_ai_setup import check_true_ai_setup
from scripts.run_v1_real_audio_pilot import run_real_audio_pilot


def test_true_ai_setup_doctor_writes_public_safe_ready_report(tmp_path: Path) -> None:
    def fake_runner(command, **kwargs):
        assert command == [".venv-ai/bin/python", "scripts/check_ai_runtime.py"]
        return subprocess.CompletedProcess(command, 0, json.dumps(_runtime_payload(true_ai_ready=True)), "")

    report = check_true_ai_setup(
        verify_input=tmp_path / "drums.wav",
        verify_output_dir=tmp_path / "verify",
        runner=fake_runner,
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "ready"
    assert report["true_ai_ready"] is True
    assert report["env"]["adtof_template"] == "configured"
    assert report["checks"]["adtof"]["event_count"] == 12
    assert_public_safe(report)


def test_true_ai_setup_doctor_reports_blocked_reason_without_raw_diagnostics(tmp_path: Path) -> None:
    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(_runtime_payload(true_ai_ready=False)), "")

    report = check_true_ai_setup(
        verify_input=tmp_path / "missing.wav",
        verify_output_dir=tmp_path / "verify",
        runner=fake_runner,
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["true_ai_ready"] is False
    assert report["checks"]["adtof"]["status_code"] == "verify_input_not_found"
    assert_public_safe(report)


def test_real_audio_pilot_rejects_repo_output_dir(tmp_path: Path) -> None:
    input_path = tmp_path / "authorized.wav"
    input_path.write_bytes(b"RIFF")

    with pytest.raises(ValueError):
        run_real_audio_pilot(input_path=input_path, output_dir=Path("pilot-output"))


def test_real_audio_pilot_writes_completed_with_blockers_report(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "authorized.wav"
    input_path.write_bytes(b"RIFF")
    output_dir = tmp_path / "pilot"

    monkeypatch.setattr(run_v1_real_audio_pilot, "check_true_ai_setup", _ready_setup)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_v1_eval", _fake_v1_eval_with_blocker)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_quality_matrix", _fake_quality_matrix_with_candidate)

    report = run_real_audio_pilot(
        input_path=input_path,
        output_dir=output_dir,
        skip_quality_matrix=False,
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "completed_with_blockers"
    assert report["input"] == {"ref": "external:authorized.wav", "exists": True, "suffix": ".wav"}
    assert report["v1_eval"]["best_real_audio"]["primary_blocker"] == "sparse_transcription"
    assert report["quality_matrix"]["candidate_thresholds"] == [{"fixture": "external:authorized.wav", "threshold": "0.4"}]
    assert report["manual_eval_seed"]["artifact_ref"] == "baseline:authorized"
    assert report["review_packet"]["status"] == "requires_completed_backend_job"
    assert (output_dir / "pilot_report.json").exists()
    assert (output_dir / "pilot_handoff.md").exists()
    assert_public_safe(report)
    assert_public_safe((output_dir / "pilot_handoff.md").read_text(encoding="utf-8"))


def test_real_audio_pilot_cli_returns_nonzero_for_completed_with_blockers(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "authorized.wav"
    input_path.write_bytes(b"RIFF")
    output_dir = tmp_path / "pilot"

    monkeypatch.setattr(run_v1_real_audio_pilot, "check_true_ai_setup", _ready_setup)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_v1_eval", _fake_v1_eval_with_blocker)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_quality_matrix", _fake_quality_matrix_with_candidate)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_v1_real_audio_pilot.py",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert real_audio_pilot_main() == 1


def test_real_audio_pilot_missing_input_writes_blocked_report(tmp_path: Path) -> None:
    report = run_real_audio_pilot(
        input_path=tmp_path / "missing.wav",
        output_dir=tmp_path / "pilot",
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["manual_eval_seed"]["blocked_reason"] == "input_file_missing"
    assert_public_safe(report)


def test_real_audio_pilot_redaction_fallback_drops_unsafe_input_filename(tmp_path: Path) -> None:
    input_path = tmp_path / "Traceback.wav"
    input_path.write_bytes(b"RIFF")

    report = run_real_audio_pilot(
        input_path=input_path,
        output_dir=tmp_path / "pilot",
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "failed"
    assert report["input"] == {"ref": "external:redacted", "exists": True, "suffix": ".wav"}
    assert_public_safe(report)
    assert_public_safe((tmp_path / "pilot" / "pilot_report.json").read_text(encoding="utf-8"))


def test_real_audio_pilot_rejects_unsafe_input_filename_before_subreports(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "stdout.wav"
    input_path.write_bytes(b"RIFF")

    def fail_if_called(*_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("unsafe filename must be rejected before upstream reports run")

    monkeypatch.setattr(run_v1_real_audio_pilot, "check_true_ai_setup", fail_if_called)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_v1_eval", fail_if_called)
    monkeypatch.setattr(run_v1_real_audio_pilot, "run_quality_matrix", fail_if_called)

    output_dir = tmp_path / "pilot"
    report = run_real_audio_pilot(
        input_path=input_path,
        output_dir=output_dir,
        checked_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert report["status"] == "failed"
    assert report["input"] == {"ref": "external:redacted", "exists": True, "suffix": ".wav"}
    assert report["manual_eval_seed"]["blocked_reason"] == "unsafe_input_filename"
    assert not (output_dir / "v1_eval").exists()
    assert not (output_dir / "quality_matrix").exists()
    assert_public_safe(report)
    assert_public_safe((output_dir / "pilot_report.json").read_text(encoding="utf-8"))


def _ready_setup(**_kwargs):
    return {"status": "ready", "true_ai_ready": True, "missing_requirements": []}


def _fake_v1_eval_with_blocker(*_args, **_kwargs):
    return {
        "status": "completed",
        "v1_readiness": {"external_fixture_count": 1, "external_human_correctable_count": 0},
        "fixtures": [
            {
                "fixture": "external:authorized.wav",
                "status": "completed",
                "human_correctable": False,
                "primary_blocker": "sparse_transcription",
                "raw_event_count": 4,
                "processed_event_count": 2,
                "processed_drum_counts": {"kick": 1, "snare": 1},
                "quality_verdict": {
                    "limitations": ["sparse_transcription"],
                    "candidate_gate": {"status": "failed", "blocking_flags": ["sparse_transcription"]},
                    "usability_score": 2,
                },
                "musicxml": {"available": True, "parseable": True},
                "manual_eval_seed": {
                    "artifact_ref": "baseline:authorized",
                    "baseline_report_ref": "runs/authorized/baseline.json",
                },
            }
        ],
    }


def _fake_quality_matrix_with_candidate(*_args, **_kwargs):
    return {
        "status": "completed_with_failures",
        "thresholds": ["0.3", "0.4", "0.5", "0.6"],
        "summary": {
            "completed_runs": 4,
            "blocked_runs": 0,
            "candidate_thresholds": [{"fixture": "external:authorized.wav", "threshold": "0.4"}],
        },
    }


def _runtime_payload(*, true_ai_ready: bool) -> dict:
    return {
        "runtime_checks": {
            "ffmpeg": {"ready": True},
            "demucs": {"ready": True},
            "adtof_pytorch": {
                "ready": true_ai_ready,
                "status_code": "ready" if true_ai_ready else "verify_input_not_found",
                "template_configured": True,
                "template_executable": True,
                "output_verified": true_ai_ready,
                "output_verification": {"event_count": 12 if true_ai_ready else None},
            },
            "local_pipeline": {
                "true_ai_ready": true_ai_ready,
                "missing_requirements": [] if true_ai_ready else ["ADTOF output verification failed"],
            },
        }
    }


def assert_public_safe(payload: object) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    for token in ("/Users/", "/private/tmp/", "/var/folders/", "Traceback", "stdout", "stderr", "raw command", "command_template"):
        assert token not in text
