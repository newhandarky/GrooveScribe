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


def _payload(*, mock_ai_ready: bool = True, true_ai_ready: bool = True) -> dict:
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
            "adtof_pytorch": {
                "ready": true_ai_ready,
                "status_code": "ready" if true_ai_ready else "verify_input_missing",
                "configured": true_ai_ready,
                "template_configured": true_ai_ready,
                "template_executable": true_ai_ready,
                "runtime_verified": true_ai_ready,
                "output_verified": true_ai_ready,
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
                    "verified": true_ai_ready,
                    "attempted": true_ai_ready,
                    "status_code": "ready" if true_ai_ready else "verify_input_missing",
                    "event_count": 7 if true_ai_ready else None,
                    "reason": None if true_ai_ready else "GROOVESCRIBE_ADTOF_VERIFY_INPUT is not set",
                },
            },
            "musescore_pdf": {
                "ready": True,
                "available_candidates": ["mscore"],
                "configured_renderer": "/tmp/private/mscore",
            },
            "local_pipeline": {
                "mock_ai_ready": mock_ai_ready,
                "true_ai_ready": true_ai_ready,
                "missing_requirements": [] if true_ai_ready else ["ADTOF runtime is not verified"],
            },
        },
        "smoke_commands": {
            "runtime_check": "PYTHONPATH=. /Users/dev/project/.venv-ai/bin/python scripts/check_ai_runtime.py",
            "local_pipeline_mock": "/Users/dev/project/.venv-ai/bin/python scripts/run_local_pipeline.py",
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
        assert env["GROOVESCRIBE_ADTOF_DEVICE"] == "mps"
        assert env["GROOVESCRIBE_ADTOF_THRESHOLD"] == "0.42"
        assert env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"] == "adtof --input {input} --output {output}"
        assert env["GROOVESCRIBE_ADTOF_CHECKPOINT"] == "/tmp/private/model.ckpt"
        assert env["GROOVESCRIBE_ADTOF_VERIFY_INPUT"] == "/tmp/private/drums.wav"
        assert env["GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"] == "/tmp/private/adtof-check"
        assert env["GROOVESCRIBE_PDF_RENDERER"] == "/tmp/private/mscore"
        return _completed(_payload(true_ai_ready=True))

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
    assert response.mock_ai_ready is True
    assert response.true_ai_ready is True
    assert response.checks["ffmpeg"]["ready"] is True
    assert response.checks["ai_python"]["executable"] == "ai-python"
    assert response.checks["adtof"]["device"] == "cpu"
    assert response.checks["adtof"]["status_code"] == "ready"
    assert response.checks["adtof"]["event_count"] == 7
    assert response.checks["adtof"]["summary"]
    assert response.checks["adtof"]["next_steps"]
    assert response.checks["musescore_pdf"]["configured_renderer"] == "<local-path>"


def test_runtime_diagnostics_degraded_response(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(_payload(mock_ai_ready=True, true_ai_ready=False)),
    )

    response = service.get_preflight()

    assert response.status == "degraded"
    assert response.mock_ai_ready is True
    assert response.true_ai_ready is False
    assert response.missing_requirements == ["ADTOF runtime is not verified"]
    assert response.checks["adtof"]["status_code"] == "verify_input_missing"
    assert response.checks["adtof"]["output_verification_reason"] == "GROOVESCRIBE_ADTOF_VERIFY_INPUT is not set"


def test_runtime_diagnostics_not_ready_response(tmp_path: Path) -> None:
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(_payload(mock_ai_ready=False, true_ai_ready=False)),
    )

    response = service.get_preflight()

    assert response.status == "not_ready"
    assert response.mock_ai_ready is False
    assert response.true_ai_ready is False


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


def test_runtime_diagnostics_redacts_adtof_output_reason(tmp_path: Path) -> None:
    payload = _payload(mock_ai_ready=True, true_ai_ready=False)
    payload["runtime_checks"]["adtof_pytorch"]["output_verification"]["reason"] = (
        "verification input does not exist: /tmp/private/drums.wav"
    )
    service = RuntimeDiagnosticsService(
        settings=_settings(tmp_path),
        process_runner=lambda *_args, **_kwargs: _completed(payload),
    )

    response = service.get_preflight()

    assert response.checks["adtof"]["output_verification_reason"] == "verification input does not exist: <local-path>"
    assert "/tmp/private" not in response.model_dump_json()
