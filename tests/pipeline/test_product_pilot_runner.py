from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.run_v1_product_pilot import PilotCommand, run_product_pilot

UNSAFE_TOKENS = (
    "/Users/",
    "/tmp/",
    "/private/tmp/",
    "/var/folders/",
    "Traceback",
    "stdout",
    "stderr",
    "raw command",
    "command_template",
)


def test_product_pilot_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_v1_product_pilot.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--output-dir" in result.stdout


def test_product_pilot_rejects_repo_output_dir() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_v1_product_pilot.py", "--output-dir", "product-pilot-output"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "output_dir_must_be_outside_repo" in result.stdout
    assert_public_safe(result.stdout + result.stderr)


def test_product_pilot_writes_passed_report_and_handoff(tmp_path: Path) -> None:
    output_dir = tmp_path / "product-pilot"

    report = run_product_pilot(output_dir=output_dir, runner=_passing_runner)
    report_text = (output_dir / "product_pilot_report.json").read_text(encoding="utf-8")
    handoff = (output_dir / "product_pilot_handoff.md").read_text(encoding="utf-8")

    assert report["schema_version"] == "1.0"
    assert report["status"] == "passed"
    assert report["output_location"] == {"status": "repo_external", "ref": "product-pilot"}
    assert report["artifact_hygiene"] == {
        "status": "passed",
        "forbidden_status_entries": [],
        "generated_artifacts_present": [],
    }
    assert report["true_ai_opt_in"]["status"] == "not_required_for_product_pilot"
    assert report["pdf_renderer"]["status"] == "optional_not_blocking"
    assert {item["name"] for item in report["usability_scenarios"]} >= {
        "upload_to_completed_result",
        "completed_rerun_flow",
        "failed_interrupted_retry_flow",
        "result_review_packet_actions",
    }
    assert all(item["status"] == "passed" for item in report["usability_scenarios"])
    assert "Product Pilot" in handoff
    assert_public_safe(report_text)
    assert_public_safe(handoff)


def test_product_pilot_failed_browser_flow_marks_scenarios_failed(tmp_path: Path) -> None:
    output_dir = tmp_path / "product-pilot-failed"

    report = run_product_pilot(output_dir=output_dir, runner=_failing_browser_runner)

    assert report["status"] == "failed"
    browser = next(item for item in report["commands"] if item["name"] == "browser_product_flow")
    assert browser["returncode"] == 1
    assert any(item["status"] == "failed" for item in report["usability_scenarios"])
    assert_public_safe(json.dumps(report, ensure_ascii=False))


def test_product_pilot_runner_exception_writes_safe_failed_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "product-pilot-runner-error"

    report = run_product_pilot(output_dir=output_dir, runner=_raising_browser_runner)
    report_text = (output_dir / "product_pilot_report.json").read_text(encoding="utf-8")
    handoff = (output_dir / "product_pilot_handoff.md").read_text(encoding="utf-8")

    assert report["status"] == "failed"
    browser = next(item for item in report["commands"] if item["name"] == "browser_product_flow")
    assert browser["returncode"] == 1
    assert browser["error_code"] == "command_runner_failed"
    assert_public_safe(report_text)
    assert_public_safe(handoff)


def test_product_pilot_flags_forbidden_git_status_artifacts(tmp_path: Path) -> None:
    report = run_product_pilot(output_dir=tmp_path / "product-pilot-artifacts", runner=_artifact_status_runner)

    assert report["status"] == "failed"
    assert report["artifact_hygiene"]["status"] == "failed"
    offenders = "\n".join(report["artifact_hygiene"]["forbidden_status_entries"])
    assert "storage/local/groovescribe.db" in offenders
    assert "frontend/dist" in offenders
    assert_public_safe(json.dumps(report, ensure_ascii=False))


def test_product_pilot_skip_browser_is_explicitly_marked(tmp_path: Path) -> None:
    report = run_product_pilot(output_dir=tmp_path / "product-pilot-skip", skip_browser=True, runner=_passing_runner)

    assert report["status"] == "passed"
    assert all(item["status"] == "skipped" for item in report["usability_scenarios"])


def _passing_runner(command: PilotCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "git_status":
        return subprocess.CompletedProcess(command.command, 0, stdout="## codex/v1-product-pilot\n", stderr="")
    return subprocess.CompletedProcess(command.command, 0, stdout="{}", stderr="")


def _failing_browser_runner(command: PilotCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "browser_product_flow":
        return subprocess.CompletedProcess(command.command, 1, stdout="Traceback at /tmp/private", stderr="stderr leaked")
    return _passing_runner(command)


def _raising_browser_runner(command: PilotCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "browser_product_flow":
        raise RuntimeError("Traceback /Users/private stdout stderr raw command")
    return _passing_runner(command)


def _artifact_status_runner(command: PilotCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "git_status":
        return subprocess.CompletedProcess(
            command.command,
            0,
            stdout=(
                "## codex/v1-product-pilot\n"
                "?? storage/local/groovescribe.db\n"
                "?? frontend/dist/index.html\n"
            ),
            stderr="",
        )
    return _passing_runner(command)


def assert_public_safe(payload: str) -> None:
    for token in UNSAFE_TOKENS:
        assert token not in payload
