from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

try:
    from scripts.redaction import find_unsafe_tokens
    from scripts.run_v1_release_gate import check_artifact_hygiene
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens
    from run_v1_release_gate import check_artifact_hygiene

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
AI_PYTHON = REPO_ROOT / ".venv-ai" / "bin" / "python"
BACKEND_PYTHON = BACKEND_ROOT / ".venv" / "bin" / "python"
FRONTEND_NODE_MODULES = REPO_ROOT / "frontend" / "node_modules"
CheckRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check local V1 launch prerequisites without starting servers.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Prefer /tmp, not repo-tracked files.")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-port-check", action="store_true", help="Skip default localhost port availability checks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = check_local_setup(
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        skip_port_check=args.skip_port_check,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] in {"passed", "warning"} else 1


def check_local_setup(
    *,
    backend_port: int = 8000,
    frontend_port: int = 5173,
    skip_port_check: bool = False,
    runner: CheckRunner | None = None,
) -> dict:
    command_runner = runner or _run_command
    checks = {
        "python_venvs": check_python_venvs(),
        "backend_import": check_backend_import(command_runner),
        "frontend_dependencies": check_frontend_dependencies(),
        "playwright_chromium": check_playwright_chromium(command_runner),
        "runtime_environment": check_runtime_environment(),
        "ports": check_ports(backend_port=backend_port, frontend_port=frontend_port, skip=skip_port_check),
        "artifact_hygiene": check_artifact_hygiene(),
    }
    report = {
        "schema_version": "1.0",
        "status": _overall_status(checks),
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "next_steps": _next_steps(checks),
    }
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_tokens": unsafe}
    if unsafe:
        report["status"] = "failed"
    return report


def check_python_venvs() -> dict:
    ai_exists = AI_PYTHON.exists()
    backend_exists = BACKEND_PYTHON.exists()
    return {
        "status": "passed" if ai_exists and backend_exists else "failed",
        "ai_python": "available" if ai_exists else "missing",
        "backend_python": "available" if backend_exists else "missing",
    }


def check_backend_import(runner: CheckRunner) -> dict:
    if not BACKEND_PYTHON.exists():
        return {"status": "failed", "reason": "backend_python_missing"}
    result = runner([BACKEND_PYTHON.as_posix(), "-c", "import app.main"], BACKEND_ROOT)
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "diagnostic": _safe_diagnostic(result.stderr or result.stdout),
    }


def check_frontend_dependencies() -> dict:
    return {
        "status": "passed" if FRONTEND_NODE_MODULES.exists() else "failed",
        "node_modules": "available" if FRONTEND_NODE_MODULES.exists() else "missing",
    }


def check_playwright_chromium(runner: CheckRunner) -> dict:
    if importlib.util.find_spec("json") is None:  # pragma: no cover - defensive stdlib guard
        return {"status": "failed", "reason": "python_json_missing"}
    result = runner(
        [
            "node",
            "-e",
            "const { chromium } = require('@playwright/test'); console.log(chromium.executablePath());",
        ],
        REPO_ROOT,
    )
    if result.returncode != 0:
        return {
            "status": "warning",
            "reason": "playwright_check_unavailable",
            "next_step": "npx playwright install chromium",
            "diagnostic": _safe_diagnostic(result.stderr or result.stdout),
        }
    executable = Path(result.stdout.strip())
    missing = not executable.exists()
    return {
        "status": "warning" if missing else "passed",
        "browser": "chromium",
        "next_step": "npx playwright install chromium" if missing else None,
    }


def check_runtime_environment() -> dict:
    required_env = "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"
    return {
        "status": "informational",
        "mock_ai": "default_release_path",
        "true_ai": "opt_in",
        "true_ai_command": "configured" if required_env in _safe_env_keys() else "not_configured",
        "pdf_renderer": "optional",
    }


def check_port_available(host: str, port: int) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        occupied = probe.connect_ex((host, port)) == 0
    return {
        "status": "blocked" if occupied else "passed",
        "host": host,
        "port": port,
        "available": not occupied,
    }


def check_ports(*, backend_port: int, frontend_port: int, skip: bool) -> dict:
    if skip:
        return {
            "backend": {"status": "skipped", "host": "127.0.0.1", "port": backend_port, "available": None},
            "frontend": {"status": "skipped", "host": "127.0.0.1", "port": frontend_port, "available": None},
        }
    return {
        "backend": check_port_available("127.0.0.1", backend_port),
        "frontend": check_port_available("127.0.0.1", frontend_port),
    }


def _run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def _overall_status(checks: dict) -> str:
    flattened = [
        checks["python_venvs"]["status"],
        checks["backend_import"]["status"],
        checks["frontend_dependencies"]["status"],
        checks["playwright_chromium"]["status"],
        checks["ports"]["backend"]["status"],
        checks["ports"]["frontend"]["status"],
        checks["artifact_hygiene"]["status"],
    ]
    if any(status in {"failed", "blocked"} for status in flattened):
        return "failed"
    if any(status == "warning" for status in flattened):
        return "warning"
    return "passed"


def _next_steps(checks: dict) -> list[str]:
    steps: list[str] = []
    if checks["python_venvs"]["status"] == "failed":
        steps.append("Create backend/.venv and .venv-ai before launching V1 locally.")
    if checks["backend_import"]["status"] == "failed":
        steps.append("Fix backend import errors before running npm run dev:local.")
    if checks["frontend_dependencies"]["status"] == "failed":
        steps.append("Run npm install before starting the frontend.")
    if checks["playwright_chromium"]["status"] == "warning":
        steps.append("Run npx playwright install chromium before browser smoke.")
    if checks["ports"]["backend"]["status"] == "blocked":
        steps.append("Free backend port or pass --backend-port to the launcher.")
    if checks["ports"]["frontend"]["status"] == "blocked":
        steps.append("Free frontend port or pass --frontend-port to the launcher.")
    if checks["artifact_hygiene"]["status"] != "passed":
        steps.append("Remove generated artifacts from git status before release sign-off.")
    return steps


def _safe_diagnostic(value: str) -> str:
    if not value.strip():
        return ""
    return "[redacted]" if find_unsafe_tokens(value) else value.strip().splitlines()[-1][:240]


def _safe_env_keys() -> set[str]:
    import os

    return set(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
