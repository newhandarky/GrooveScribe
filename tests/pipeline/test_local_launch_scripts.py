from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_v1_local_setup as local_setup
from scripts.run_v1_local_dev import build_process_specs, format_setup_failure, setup_failure_issues


def test_local_setup_report_passes_with_safe_prerequisites(tmp_path: Path, monkeypatch) -> None:
    ai_python = tmp_path / "ai-python"
    backend_python = tmp_path / "backend-python"
    frontend_modules = tmp_path / "node_modules"
    chromium = tmp_path / "chromium"
    for path in (ai_python, backend_python, chromium):
        path.write_text("", encoding="utf-8")
    frontend_modules.mkdir()
    monkeypatch.setattr(local_setup, "AI_PYTHON", ai_python)
    monkeypatch.setattr(local_setup, "BACKEND_PYTHON", backend_python)
    monkeypatch.setattr(local_setup, "FRONTEND_NODE_MODULES", frontend_modules)
    monkeypatch.setattr(local_setup, "check_port_available", _fake_available_port)

    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command[0] == "node":
            return subprocess.CompletedProcess(command, 0, stdout=f"{chromium}\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    report = local_setup.check_local_setup(backend_port=8000, frontend_port=5173, runner=fake_runner)

    assert report["schema_version"] == "1.0"
    assert report["status"] == "passed"
    assert report["checks"]["backend_import"]["status"] == "passed"
    assert report["checks"]["playwright_chromium"]["status"] == "passed"
    assert report["checks"]["runtime_environment"]["true_ai"] == "opt_in"
    assert report["redaction"]["status"] == "passed"
    assert_no_unsafe_tokens(report)


def test_local_setup_reports_missing_dependencies_without_sensitive_diagnostics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_setup, "AI_PYTHON", tmp_path / "missing-ai-python")
    monkeypatch.setattr(local_setup, "BACKEND_PYTHON", tmp_path / "missing-backend-python")
    monkeypatch.setattr(local_setup, "FRONTEND_NODE_MODULES", tmp_path / "missing-node-modules")
    monkeypatch.setattr(local_setup, "check_port_available", _fake_available_port)

    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="stdout leaked",
            stderr="Traceback at /Users/private/project",
        )

    report = local_setup.check_local_setup(backend_port=8000, frontend_port=5173, runner=fake_runner)

    assert report["status"] == "failed"
    assert report["checks"]["python_venvs"]["status"] == "failed"
    assert report["checks"]["backend_import"]["reason"] == "backend_python_missing"
    assert report["checks"]["frontend_dependencies"]["status"] == "failed"
    assert report["redaction"]["status"] == "passed"
    assert_no_unsafe_tokens(report)


def test_local_setup_marks_occupied_port_blocked(monkeypatch) -> None:
    class FakeSocket:
        def __enter__(self) -> "FakeSocket":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, _timeout: float) -> None:
            return None

        def connect_ex(self, _address: tuple[str, int]) -> int:
            return 0

    monkeypatch.setattr(local_setup.socket, "socket", lambda *_args, **_kwargs: FakeSocket())
    report = local_setup.check_port_available("127.0.0.1", 8000)

    assert report == {
        "status": "blocked",
        "host": "127.0.0.1",
        "port": 8000,
        "available": False,
    }


def test_local_dev_launcher_builds_backend_and_frontend_commands() -> None:
    specs = build_process_specs(host="127.0.0.1", backend_port=9000, frontend_port=5174)

    assert [spec.name for spec in specs] == ["backend", "frontend"]
    assert specs[0].command == [
        ".venv/bin/python",
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "9000",
    ]
    assert specs[1].command == [
        "npm",
        "--prefix",
        "frontend",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5174",
    ]
    assert specs[1].env == {"VITE_API_PROXY_TARGET": "http://127.0.0.1:9000"}


def test_local_dev_launcher_formats_blocked_port_failure_without_raw_diagnostics() -> None:
    setup = {
        "status": "failed",
        "checks": {
            "python_venvs": {"status": "passed"},
            "ports": {
                "backend": {"status": "blocked", "host": "127.0.0.1", "port": 8000, "available": False},
                "frontend": {"status": "passed", "host": "127.0.0.1", "port": 5173, "available": True},
            },
        },
        "next_steps": ["Free backend port or pass --backend-port to the launcher."],
        "redaction": {"status": "passed", "unsafe_tokens": []},
    }

    assert setup_failure_issues(setup) == ["ports.backend: blocked (127.0.0.1:8000)"]
    rendered = format_setup_failure(setup)

    assert "Local setup check failed:" in rendered
    assert "ports.backend: blocked (127.0.0.1:8000)" in rendered
    assert "Free backend port or pass --backend-port to the launcher." in rendered
    assert_no_unsafe_tokens(rendered)


def test_local_dev_launcher_formats_dependency_failure_without_sensitive_details() -> None:
    setup = {
        "status": "failed",
        "checks": {
            "python_venvs": {"status": "failed"},
            "backend_import": {"status": "failed", "reason": "backend_python_missing"},
            "ports": {
                "backend": {"status": "passed", "host": "127.0.0.1", "port": 8000, "available": True},
                "frontend": {"status": "passed", "host": "127.0.0.1", "port": 5173, "available": True},
            },
        },
        "next_steps": ["Create backend/.venv and .venv-ai before launching V1 locally."],
        "redaction": {"status": "passed", "unsafe_tokens": []},
    }

    rendered = format_setup_failure(setup)

    assert "python_venvs: failed" in rendered
    assert "backend_import: failed (backend_python_missing)" in rendered
    assert "Create backend/.venv and .venv-ai before launching V1 locally." in rendered
    assert_no_unsafe_tokens(rendered)


def _fake_available_port(host: str, port: int) -> dict:
    return {"status": "passed", "host": host, "port": port, "available": True}


def assert_no_unsafe_tokens(payload: object) -> None:
    rendered = json.dumps(payload, ensure_ascii=False)
    for token in ("/Users/", "/tmp/", "/private/tmp/", "/var/folders/", "Traceback", "stdout", "stderr", "raw command", "command_template"):
        assert token not in rendered
