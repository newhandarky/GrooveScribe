from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.services.runtime_diagnostics import RuntimeDiagnosticsService


def _settings(tmp_path: Path, **overrides) -> Settings:
    ai_python = tmp_path / "ai-python"
    ai_python.write_text("#!/bin/sh\n", encoding="utf-8")
    values = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "storage_root": str(tmp_path / "storage"),
        "ai_python_path": str(ai_python),
    }
    values.update(overrides)
    return Settings(**values)


def _payload(*, demo_mock_ready: bool = True, generic_baseline_ready: bool = True, adtof_ready: bool = False) -> dict:
    return {
        "commands": {
            "ffmpeg": {
                "available": True,
                "path": "/Users/dev/bin/ffmpeg",
                "version": "ffmpeg version 8.0",
            }
        },
        "runtime_checks": {
            "ffmpeg": {"ready": True},
            "demucs": {
                "ready": True,
                "package": {"available": True, "version": "4.0.1"},
                "command_probe": {"exit_code": 0},
            },
            "spectral_onset": {
                "ready": generic_baseline_ready,
                "reason_code": None if generic_baseline_ready else "librosa_runtime_unavailable",
            },
            "adtof_pytorch": {
                "ready": adtof_ready,
                "status_code": "ready" if adtof_ready else "verify_input_missing",
                "configured": adtof_ready,
                "template_configured": adtof_ready,
                "template_executable": adtof_ready,
                "runtime_verified": adtof_ready,
                "output_verified": adtof_ready,
                "device": "cpu",
                "threshold": "0.5",
                "missing_placeholders": [],
                "required_env": ["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"],
                "optional_env": [
                    "GROOVESCRIBE_ADTOF_CHECKPOINT",
                    "GROOVESCRIBE_ADTOF_VERIFY_INPUT",
                    "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR",
                ],
                "output_verification": {
                    "verified": adtof_ready,
                    "attempted": adtof_ready,
                    "status_code": "ready" if adtof_ready else "verify_input_missing",
                    "event_count": 7 if adtof_ready else None,
                    "reason": None if adtof_ready else "GROOVESCRIBE_ADTOF_VERIFY_INPUT is not set",
                },
            },
            "musescore_pdf": {
                "ready": True,
                "available_candidates": ["mscore"],
                "configured_renderer": "/tmp/private/mscore",
            },
            "local_pipeline": {
                "demo_mock_ready": demo_mock_ready,
                "generic_baseline_ready": generic_baseline_ready,
                "missing_requirements": [] if generic_baseline_ready else ["Demucs package/command probe is not ready"],
            },
        },
        "smoke_commands": {
            "runtime_check": "PYTHONPATH=. /Users/dev/project/.venv-ai/bin/python scripts/check_ai_runtime.py",
            "local_pipeline_generic_baseline": "/Users/dev/project/.venv-ai/bin/python scripts/run_local_pipeline.py",
            "tmp_command": "/tmp/private/tool --input demo.wav",
        },
    }


def _completed(payload: dict, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["python", "script.py"], returncode, stdout=json.dumps(payload), stderr="")


def test_runtime_diagnostics_ready_response(tmp_path: Path) -> None:
    def fake_runner(command, **kwargs):
        assert command[0].endswith("ai-python")
        assert kwargs["cwd"]
        assert kwargs["timeout"] == 30
        env = kwargs["env"]
        assert env["GROOVESCRIBE_DEMUCS_DEVICE"] == "cpu"
        assert not any(key.startswith("GROOVESCRIBE_ADTOF_") for key in env)
        assert env["GROOVESCRIBE_PDF_RENDERER"] == "/tmp/private/mscore"
        return _completed(_payload(generic_baseline_ready=True, adtof_ready=True))

    response = RuntimeDiagnosticsService(
        settings=_settings(
            tmp_path,
            pipeline_demucs_device="cpu",
            pipeline_adtof_device="mps",
            pipeline_adtof_threshold=0.42,
            pipeline_adtof_command_template="adtof --input {input} --output {output}",
            pipeline_adtof_checkpoint_path="/tmp/private/model.ckpt",
            pipeline_adtof_verify_input_path="/tmp/private/drums.wav",
            pipeline_adtof_verify_output_dir="/tmp/private/adtof-check",
            pipeline_pdf_renderer="/tmp/private/mscore",
        ),
        process_runner=fake_runner,
    ).get_preflight()

    assert response.status == "ready"
    assert response.generic_baseline_ready is True
    assert response.demo_mock_ready is True
    assert response.checks["ffmpeg"]["ready"] is True
    assert response.checks["ai_python"]["executable"] == "ai-python"
    assert response.checks["spectral_onset"]["ready"] is True
    assert response.offline_evaluation == {"adtof": {"enabled": False, "reason": "offline_evaluation_only"}}
    assert response.mock_ai_ready is True
    assert response.true_ai_ready is False
    assert response.checks["musescore_pdf"]["configured_renderer"] == "<local-path>"


def test_runtime_diagnostics_degraded_response(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(_payload(demo_mock_ready=True, generic_baseline_ready=False)),
    )

    response = service.get_preflight()

    assert response.status == "degraded"
    assert response.demo_mock_ready is True
    assert response.generic_baseline_ready is False
    assert response.missing_requirements == ["Demucs package/command probe is not ready"]
    assert response.checks["spectral_onset"]["reason_code"] == "librosa_runtime_unavailable"
    assert response.offline_evaluation["adtof"]["enabled"] is False


def test_runtime_diagnostics_not_ready_response(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(_payload(demo_mock_ready=False, generic_baseline_ready=False)),
    )

    response = service.get_preflight()

    assert response.status == "not_ready"
    assert response.demo_mock_ready is False
    assert response.generic_baseline_ready is False


def test_runtime_diagnostics_timeout_returns_error(tmp_path: Path) -> None:
    def fake_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["python"], timeout=30)

    response = RuntimeDiagnosticsService(settings=_settings(tmp_path), process_runner=fake_runner).get_preflight()

    assert response.status == "error"
    assert response.error.code == "RUNTIME_PREFLIGHT_TIMEOUT"


def test_runtime_diagnostics_nonzero_exit_returns_error(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["python"],
            2,
            stdout="",
            stderr="Traceback at /Users/dev/private",
        ),
    )

    response = service.get_preflight()

    assert response.status == "error"
    assert response.error.code == "RUNTIME_PREFLIGHT_FAILED"
    assert "Traceback" not in response.error.message
    assert "/Users/dev/private" not in response.error.message


def test_runtime_diagnostics_invalid_json_returns_error(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(["python"], 0, stdout="not-json", stderr=""),
    )

    response = service.get_preflight()

    assert response.status == "error"
    assert response.error.code == "RUNTIME_PREFLIGHT_INVALID_JSON"


def test_runtime_diagnostics_missing_ai_python_returns_error(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path, ai_python_path=str(tmp_path / "missing-python")),
        process_runner=lambda *_args, **_kwargs: _completed(_payload()),
    )

    response = service.get_preflight()

    assert response.status == "error"
    assert response.error.code == "AI_PYTHON_NOT_FOUND"
    assert response.checks["ai_python"]["available"] is False


def test_runtime_diagnostics_redacts_local_paths_from_smoke_commands(tmp_path: Path) -> None:
    response = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(_payload()),
    ).get_preflight()

    encoded = response.model_dump_json()
    assert "/Users/dev" not in encoded
    assert "Traceback" not in encoded
    assert "<local-path>" in encoded


def test_runtime_diagnostics_preflight_strips_adtof_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE", "adtof --input {input} --output {output}")
    captured_env = {}

    def fake_runner(*_args, **kwargs):
        captured_env.update(kwargs["env"])
        return _completed(_payload())

    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=fake_runner,
    )

    service.get_preflight()

    assert "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" not in captured_env
