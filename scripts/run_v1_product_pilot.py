from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.redaction import find_unsafe_tokens
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-v1-product-pilot")
REPORT_FILENAME = "product_pilot_report.json"
HANDOFF_FILENAME = "product_pilot_handoff.md"


@dataclass(frozen=True)
class PilotCommand:
    name: str
    command: list[str]
    cwd: Path = REPO_ROOT


CommandRunner = Callable[[PilotCommand], subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GrooveScribe V1 end-to-end product pilot.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-browser", action="store_true", help="Skip Playwright browser flow for local debugging only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if _inside_repo(args.output_dir):
        print(json.dumps(_failure("output_dir_must_be_outside_repo"), ensure_ascii=False, indent=2))
        return 2
    report = run_product_pilot(output_dir=args.output_dir, skip_browser=args.skip_browser)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": report["status"],
                "report": REPORT_FILENAME,
                "handoff": HANDOFF_FILENAME,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 1


def run_product_pilot(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_browser: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    if _inside_repo(output_dir):
        raise ValueError("output_dir_must_be_outside_repo")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command_runner = runner or _run_command
    _cleanup_generated_artifacts()
    commands = _commands(skip_browser=skip_browser)
    results = [_run_safe(command, command_runner) for command in commands]
    _cleanup_generated_artifacts()
    git_status = _command_by_name(results, "git_status")
    artifact_hygiene = _artifact_hygiene(git_status)
    scenarios = _scenarios(skip_browser=skip_browser, browser_passed=_passed(results, "browser_product_flow"))
    status = "passed" if all(item["returncode"] == 0 for item in results) and artifact_hygiene["status"] == "passed" else "failed"
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "output_location": {"status": "repo_external", "ref": output_dir.name},
        "commands": _command_summary(results),
        "artifact_hygiene": artifact_hygiene,
        "usability_scenarios": scenarios,
        "true_ai_opt_in": {"status": "not_required_for_product_pilot"},
        "pdf_renderer": {"status": "optional_not_blocking"},
        "next_steps": _next_steps(status, scenarios),
        "redaction": {"status": "passed", "unsafe_token_count": 0},
    }
    report = _finalize_redaction(report)
    _write_json(output_dir / REPORT_FILENAME, report)
    _write_text(output_dir / HANDOFF_FILENAME, _render_handoff(report))
    return report


def _commands(*, skip_browser: bool) -> list[PilotCommand]:
    commands = [
        PilotCommand("local_setup", [sys.executable, "scripts/check_v1_local_setup.py", "--skip-port-check"]),
        PilotCommand(
            "backend_product_contract",
            [
                ".venv/bin/python",
                "-m",
                "pytest",
                "tests/test_transcription_apis.py",
                "tests/test_transcription_api_integration.py",
                "tests/test_job_history_and_retry_api.py",
            ],
            cwd=REPO_ROOT / "backend",
        ),
    ]
    if not skip_browser:
        commands.append(PilotCommand("browser_product_flow", ["npm", "run", "test:e2e"]))
    commands.extend(
        [
            PilotCommand("git_status", ["git", "status", "--short", "--branch"]),
            PilotCommand("git_diff_check", ["git", "diff", "--check"]),
        ]
    )
    return commands


def _cleanup_generated_artifacts() -> None:
    for relative in (
        "frontend/dist",
        "test-results",
        "playwright-report",
        "blob-report",
    ):
        path = REPO_ROOT / relative
        if path.exists():
            shutil.rmtree(path)


def _run_safe(command: PilotCommand, runner: CommandRunner) -> dict[str, Any]:
    completed = runner(command)
    result: dict[str, Any] = {
        "name": command.name,
        "returncode": completed.returncode,
        "cwd": _safe_cwd(command.cwd),
    }
    if command.name == "git_status":
        result["safe_output"] = "" if find_unsafe_tokens(completed.stdout) else completed.stdout
    return result


def _run_command(command: PilotCommand) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command.command, cwd=command.cwd, capture_output=True, text=True, check=False)


def _scenarios(*, skip_browser: bool, browser_passed: bool) -> list[dict[str, str]]:
    browser_status = "skipped" if skip_browser else "passed" if browser_passed else "failed"
    return [
        {"name": "upload_to_completed_result", "status": browser_status},
        {"name": "result_review_packet_actions", "status": browser_status},
        {"name": "midi_musicxml_download_visibility", "status": browser_status},
        {"name": "pdf_optional_status_visibility", "status": browser_status},
        {"name": "job_history_visibility", "status": browser_status},
        {"name": "completed_rerun_flow", "status": browser_status},
        {"name": "failed_interrupted_retry_flow", "status": browser_status},
        {"name": "local_data_dry_run_visibility", "status": browser_status},
    ]


def _artifact_hygiene(git_status: dict[str, Any] | None) -> dict[str, Any]:
    output = str((git_status or {}).get("safe_output") or "")
    forbidden = [
        line
        for line in output.splitlines()
        if any(
            token in line
            for token in (
                "frontend/dist",
                "playwright-report",
                "test-results",
                "blob-report",
                ".sqlite",
                ".db",
            )
        )
    ]
    return {"status": "passed" if not forbidden else "failed", "forbidden_status_entries": forbidden}


def _command_by_name(results: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in results if item["name"] == name), None)


def _passed(results: list[dict[str, Any]], name: str) -> bool:
    item = _command_by_name(results, name)
    return bool(item and item["returncode"] == 0)


def _command_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": item["name"], "returncode": item["returncode"], "cwd": item["cwd"]} for item in results]


def _safe_cwd(path: Path) -> str:
    try:
        return "." if path.resolve() == REPO_ROOT else path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "[external]"


def _next_steps(status: str, scenarios: list[dict[str, str]]) -> list[str]:
    if status == "passed":
        return ["Run one manual localhost pilot with a representative audio file.", "Record any human usability friction as product issues."]
    failed = [item["name"] for item in scenarios if item["status"] == "failed"]
    return [f"Fix failed product pilot scenarios: {', '.join(failed) or 'command failure'}."]


def _finalize_redaction(report: dict[str, Any]) -> dict[str, Any]:
    rendered = json.dumps(report, ensure_ascii=False)
    unsafe = find_unsafe_tokens(rendered)
    if not unsafe:
        return report
    return {
        "schema_version": "1.0",
        "status": "failed",
        "checked_at": datetime.now(UTC).isoformat(),
        "output_location": report.get("output_location", {"status": "repo_external", "ref": "product-pilot"}),
        "commands": report.get("commands", []),
        "artifact_hygiene": {"status": "unknown", "forbidden_status_entries": []},
        "usability_scenarios": [],
        "true_ai_opt_in": {"status": "not_required_for_product_pilot"},
        "pdf_renderer": {"status": "optional_not_blocking"},
        "next_steps": ["Redaction failed while building product pilot report."],
        "redaction": {"status": "failed", "unsafe_token_count": len(unsafe)},
    }


def _render_handoff(report: dict[str, Any]) -> str:
    lines = [
        "# GrooveScribe V1 Product Pilot",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Checked at: `{report.get('checked_at')}`",
        f"- Output: `{(report.get('output_location') or {}).get('ref', 'product-pilot')}`",
        "",
        "## Scenario Summary",
        "",
    ]
    for item in report.get("usability_scenarios", []):
        lines.append(f"- `{item.get('name')}`: `{item.get('status')}`")
    lines.extend(["", "## Next Steps", ""])
    for step in report.get("next_steps", []):
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- true-AI remains opt-in.",
            "- PDF renderer remains optional.",
            "- Generated pilot reports stay outside git.",
        ]
    )
    rendered = "\n".join(lines) + "\n"
    return "[redacted]\n" if find_unsafe_tokens(rendered) else rendered


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


def _inside_repo(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _failure(error: str) -> dict[str, str]:
    return {"schema_version": "1.0", "status": "failed", "error": error}


if __name__ == "__main__":
    raise SystemExit(main())
