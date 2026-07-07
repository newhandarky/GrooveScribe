from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.check_v1_local_setup import check_local_setup
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from check_v1_local_setup import check_local_setup

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"


@dataclass(frozen=True)
class DevProcessSpec:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GrooveScribe V1 backend and frontend for local development.")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip setup checks before starting servers.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skip_doctor:
        setup = check_local_setup(backend_port=args.backend_port, frontend_port=args.frontend_port)
        if setup["status"] == "failed":
            print(format_setup_failure(setup), file=sys.stderr)
            return 1
    specs = build_process_specs(host=args.host, backend_port=args.backend_port, frontend_port=args.frontend_port)
    return run_processes(specs)


def format_setup_failure(setup: dict) -> str:
    lines = ["Local setup check failed:"]
    for issue in setup_failure_issues(setup):
        lines.append(f"- {issue}")
    next_steps = [str(step) for step in setup.get("next_steps", []) if str(step).strip()]
    if next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {step}" for step in next_steps)
    lines.append("Run npm run check:local for the full setup report.")
    return "\n".join(lines)


def setup_failure_issues(setup: dict) -> list[str]:
    checks = setup.get("checks", {})
    issues: list[str] = []
    for name, check in checks.items():
        if name == "ports" and isinstance(check, dict):
            for port_name, port_check in check.items():
                if isinstance(port_check, dict) and port_check.get("status") in {"failed", "blocked"}:
                    issues.append(
                        f"ports.{port_name}: {port_check.get('status')} "
                        f"({port_check.get('host')}:{port_check.get('port')})"
                    )
            continue
        if isinstance(check, dict) and check.get("status") in {"failed", "blocked"}:
            reason = check.get("reason")
            suffix = f" ({reason})" if reason else ""
            issues.append(f"{name}: {check.get('status')}{suffix}")
    if setup.get("redaction", {}).get("status") == "failed":
        issues.append("redaction: failed")
    return issues or [f"setup status: {setup.get('status', 'failed')}"]


def build_process_specs(*, host: str = "127.0.0.1", backend_port: int = 8000, frontend_port: int = 5173) -> list[DevProcessSpec]:
    api_proxy_target = f"http://{host}:{backend_port}"
    return [
        DevProcessSpec(
            name="backend",
            command=[
                ".venv/bin/python",
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                host,
                "--port",
                str(backend_port),
            ],
            cwd=BACKEND_ROOT,
        ),
        DevProcessSpec(
            name="frontend",
            command=[
                "npm",
                "--prefix",
                "frontend",
                "run",
                "dev",
                "--",
                "--host",
                host,
                "--port",
                str(frontend_port),
            ],
            cwd=REPO_ROOT,
            env={"VITE_API_PROXY_TARGET": api_proxy_target},
        ),
    ]


def run_processes(specs: list[DevProcessSpec]) -> int:
    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop_processes() -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 8
        for process in processes:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()

    def handle_signal(_signum: int, _frame: object) -> None:
        stop_processes()

    previous_sigint = signal.signal(signal.SIGINT, handle_signal)
    previous_sigterm = signal.signal(signal.SIGTERM, handle_signal)
    try:
        for spec in specs:
            env = None if spec.env is None else {**os.environ, **spec.env}
            processes.append(subprocess.Popen(spec.command, cwd=spec.cwd, env=env))
        while True:
            for process in processes:
                returncode = process.poll()
                if returncode is not None:
                    stop_processes()
                    return returncode
            time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
