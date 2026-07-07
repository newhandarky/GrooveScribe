from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

try:
    from scripts.redaction import find_unsafe_tokens
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ARTIFACTS = (
    Path("frontend/dist"),
    Path("test-results"),
    Path("playwright-report"),
    Path("blob-report"),
)
STATUS_FORBIDDEN_SUBSTRINGS = (
    "frontend/dist",
    "storage/",
    "backend/storage/",
    "worker/storage/",
    ".db",
    ".sqlite",
    ".sqlite3",
    "tmp",
    "playwright-report",
    "test-results",
    "blob-report",
)


@dataclass(frozen=True)
class GateCommand:
    name: str
    command: list[str]
    cwd: Path = REPO_ROOT
    env: dict[str, str] | None = None


CommandRunner = Callable[[GateCommand], subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic GrooveScribe V1 release gate.")
    parser.add_argument("--output", type=Path, help="Optional report output path. Prefer /tmp, not repo-tracked files.")
    parser.add_argument("--include-true-ai", action="store_true", help="Run opt-in true-AI smoke tests.")
    parser.add_argument("--skip-browser", action="store_true", help="Developer shortcut; not for final release signoff.")
    parser.add_argument("--skip-build", action="store_true", help="Developer shortcut; not for final release signoff.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_gate(
        include_true_ai=args.include_true_ai,
        skip_browser=args.skip_browser,
        skip_build=args.skip_build,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


def run_gate(
    *,
    include_true_ai: bool = False,
    skip_browser: bool = False,
    skip_build: bool = False,
    runner: CommandRunner | None = None,
) -> dict:
    command_runner = runner or _run_command
    started_at = datetime.now(UTC).isoformat()
    commands = []
    initial_cleanup = cleanup_generated_artifacts()
    pre_hygiene = check_artifact_hygiene()
    if pre_hygiene["status"] != "passed":
        pre_hygiene["initial_generated_cleanup"] = initial_cleanup
        return _report("failed", started_at, commands, pre_hygiene, {}, {}, {}, {}, {}, _true_ai_summary(False, []))
    pre_hygiene["initial_generated_cleanup"] = initial_cleanup

    steps = _deterministic_steps(skip_browser=skip_browser, skip_build=skip_build)
    for step in steps:
        result = command_runner(step)
        command_report = _command_report(step, result)
        commands.append(command_report)
        if result.returncode != 0:
            cleanup_generated_artifacts()
            return _report(
                "failed",
                started_at,
                commands,
                check_artifact_hygiene(),
                redaction_summary(commands),
                _local_setup_summary(commands),
                _manual_eval_summary(commands),
                _browser_summary(skip_browser, commands),
                _cleanup_summary(commands),
                _true_ai_summary(False, []),
            )

    true_ai_commands = []
    if include_true_ai:
        for step in _true_ai_steps():
            result = command_runner(step)
            command_report = _command_report(step, result)
            commands.append(command_report)
            true_ai_commands.append(command_report)
            if result.returncode != 0:
                break

    cleanup_generated_artifacts()
    artifact_hygiene = check_artifact_hygiene()
    redaction = redaction_summary(commands)
    status = "passed"
    if artifact_hygiene["status"] != "passed" or redaction["status"] != "passed":
        status = "failed"
    if include_true_ai and any(item["returncode"] != 0 for item in true_ai_commands):
        status = "failed"

    return _report(
        status,
        started_at,
        commands,
        artifact_hygiene,
        redaction,
        _local_setup_summary(commands),
        _manual_eval_summary(commands),
        _browser_summary(skip_browser, commands),
        _cleanup_summary(commands),
        _true_ai_summary(include_true_ai, true_ai_commands),
    )


def check_artifact_hygiene() -> dict:
    status = subprocess.run(
        ["git", "status", "--short", "--branch", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    offenders = [
        line
        for line in lines
        if not line.startswith("## ")
        and any(token in line for token in STATUS_FORBIDDEN_SUBSTRINGS)
    ]
    generated_present = [path.as_posix() for path in GENERATED_ARTIFACTS if (REPO_ROOT / path).exists()]
    return {
        "status": "passed" if not offenders and not generated_present else "failed",
        "branch": lines[0] if lines else "",
        "forbidden_status_entries": offenders,
        "generated_artifacts_present": generated_present,
    }


def cleanup_generated_artifacts() -> list[str]:
    removed = []
    for relative_path in GENERATED_ARTIFACTS:
        path = REPO_ROOT / relative_path
        if path.exists():
            shutil.rmtree(path)
            removed.append(relative_path.as_posix())
    return removed


def redaction_summary(payload: object) -> dict:
    unsafe = find_unsafe_tokens(json.dumps(payload, ensure_ascii=False))
    return {
        "status": "passed" if not unsafe else "failed",
        "unsafe_tokens": unsafe,
    }


def _deterministic_steps(*, skip_browser: bool, skip_build: bool) -> list[GateCommand]:
    steps = [
        GateCommand(
            "backend_targeted",
            [
                ".venv/bin/python",
                "-m",
                "pytest",
                "tests/test_transcription_api_integration.py",
                "tests/test_runtime_preflight_api.py",
                "tests/test_transcription_apis.py",
                "tests/test_local_job_recovery.py",
            ],
            cwd=REPO_ROOT / "backend",
        ),
        GateCommand(
            "pipeline_fast",
            [
                ".venv-ai/bin/python",
                "-m",
                "pytest",
                "tests/pipeline/test_true_ai_smoke_baseline.py",
                "tests/pipeline/test_manual_eval_row_generator.py",
                "tests/pipeline/test_notation_generation.py",
                "tests/pipeline/test_midi_inspection.py",
                "tests/pipeline/test_release_gate_scripts.py",
                "tests/pipeline/test_local_launch_scripts.py",
                "tests/pipeline/test_review_packet_export.py",
                "tests/pipeline/test_rc_pilot_handoff.py",
            ],
        ),
        GateCommand("local_setup", [sys.executable, "scripts/check_v1_local_setup.py", "--skip-port-check"]),
        GateCommand("frontend_test", ["npm", "--prefix", "frontend", "run", "test"]),
        GateCommand("frontend_lint", ["npm", "--prefix", "frontend", "run", "lint"]),
        GateCommand("manual_eval_gate", [sys.executable, "scripts/check_manual_eval_gate.py"]),
        GateCommand("cleanup_dry_run", [sys.executable, "scripts/cleanup_storage.py"]),
    ]
    if not skip_build:
        steps.append(GateCommand("frontend_build", ["npm", "--prefix", "frontend", "run", "build"]))
    if not skip_browser:
        steps.append(GateCommand("browser_smoke", ["npm", "run", "test:e2e"]))
    return steps


def _true_ai_steps() -> list[GateCommand]:
    env = {**os.environ, "RUN_TRUE_AI_SMOKE": "1"}
    return [
        GateCommand(
            "pipeline_true_ai_opt_in",
            [".venv-ai/bin/python", "-m", "pytest", "tests/pipeline", "-k", "true_ai_smoke"],
            env=env,
        ),
        GateCommand(
            "backend_true_ai_opt_in",
            ["backend/.venv/bin/python", "-m", "pytest", "backend/tests/test_pipeline_service_true_ai_smoke.py"],
            env=env,
        ),
    ]


def _run_command(step: GateCommand) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        step.command,
        cwd=step.cwd,
        env=step.env,
        capture_output=True,
        text=True,
        check=False,
    )


def _command_report(step: GateCommand, result: subprocess.CompletedProcess[str]) -> dict:
    return {
        "name": step.name,
        "command": _safe_command(step.command),
        "cwd": _relative_cwd(step.cwd),
        "returncode": result.returncode,
        "output_tail": _safe_tail(result.stdout),
        "diagnostic_tail": _safe_tail(result.stderr),
    }


def _safe_tail(value: str, *, max_lines: int = 20) -> list[str]:
    lines = value.splitlines()
    return [_safe_line(line) for line in lines[-max_lines:]]


def _safe_line(value: str) -> str:
    return "[redacted]" if find_unsafe_tokens(value) else value


def _safe_command(command: list[str]) -> str:
    return " ".join(_safe_command_part(item) for item in command)


def _safe_command_part(value: str) -> str:
    if find_unsafe_tokens(value):
        path = Path(value)
        return path.name if path.name else "[redacted]"
    return value


def _relative_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix() or "."
    except ValueError:
        return path.name


def _manual_eval_summary(commands: list[dict]) -> dict:
    return _command_status("manual_eval_gate", commands)


def _local_setup_summary(commands: list[dict]) -> dict:
    return _command_status("local_setup", commands)


def _browser_summary(skip_browser: bool, commands: list[dict]) -> dict:
    if skip_browser:
        return {"status": "skipped_developer_shortcut"}
    return _command_status("browser_smoke", commands)


def _cleanup_summary(commands: list[dict]) -> dict:
    return _command_status("cleanup_dry_run", commands)


def _true_ai_summary(include_true_ai: bool, commands: list[dict]) -> dict:
    if not include_true_ai:
        return {"status": "skipped_opt_in"}
    if not commands:
        return {"status": "not_run"}
    return {
        "status": "passed" if all(item["returncode"] == 0 for item in commands) else "blocked_or_failed",
        "commands": commands,
    }


def _command_status(name: str, commands: list[dict]) -> dict:
    matches = [item for item in commands if item["name"] == name]
    if not matches:
        return {"status": "not_run"}
    return {"status": "passed" if matches[-1]["returncode"] == 0 else "failed", "returncode": matches[-1]["returncode"]}


def _report(
    status: str,
    checked_at: str,
    commands: list[dict],
    artifact_hygiene: dict,
    redaction: dict,
    local_setup: dict,
    manual_eval: dict,
    browser_smoke: dict,
    cleanup: dict,
    true_ai_opt_in: dict,
) -> dict:
    return {
        "schema_version": "1.0",
        "status": status,
        "checked_at": checked_at,
        "commands": commands,
        "artifact_hygiene": artifact_hygiene,
        "redaction": redaction,
        "local_setup": local_setup,
        "manual_eval": manual_eval,
        "browser_smoke": browser_smoke,
        "cleanup": cleanup,
        "true_ai_opt_in": true_ai_opt_in,
    }


if __name__ == "__main__":
    raise SystemExit(main())
