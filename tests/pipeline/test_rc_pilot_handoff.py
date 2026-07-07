from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import run_v1_rc_pilot as rc_pilot
from scripts.check_v1_rc_handoff import check_rc_handoff
from scripts.run_v1_rc_pilot import RcCommand, run_rc_pilot

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


def test_rc_pilot_and_validator_help_are_available() -> None:
    runner = subprocess.run(
        [sys.executable, "scripts/run_v1_rc_pilot.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    validator = subprocess.run(
        [sys.executable, "scripts/check_v1_rc_handoff.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert runner.returncode == 0
    assert "--output-dir" in runner.stdout
    assert validator.returncode == 0
    assert "rc_manifest" in validator.stdout or "manifest" in validator.stdout


def test_rc_pilot_rejects_repo_output_dir() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_v1_rc_pilot.py", "--output-dir", "rc-output"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "output_dir_must_be_outside_repo" in result.stdout
    assert_public_safe(result.stdout + result.stderr)


def test_rc_pilot_writes_passed_manifest_and_handoff_with_mocked_commands(tmp_path: Path) -> None:
    output_dir = tmp_path / "rc"
    manifest = run_rc_pilot(output_dir=output_dir, runner=_passing_runner)
    handoff = (output_dir / "rc_handoff.md").read_text(encoding="utf-8")
    manifest_text = (output_dir / "rc_manifest.json").read_text(encoding="utf-8")
    release_gate_text = (output_dir / "release_gate_report.json").read_text(encoding="utf-8")
    release_gate_report = json.loads(release_gate_text)
    validation = check_rc_handoff(output_dir / "rc_manifest.json")

    assert manifest["schema_version"] == "1.0"
    assert manifest["status"] == "passed"
    assert manifest["output_location"] == {"status": "repo_external", "ref": "rc"}
    assert manifest["release_gate"]["status"] == "passed"
    assert manifest["release_evidence"]["status"] == "passed"
    assert manifest["browser_smoke"]["status"] == "passed"
    assert manifest["manual_eval"]["status"] == "passed"
    assert manifest["review_packet"]["status"] == "capability_available"
    assert manifest["true_ai_opt_in"]["status"] == "skipped_opt_in"
    assert manifest["redaction"] == {"status": "passed", "unsafe_token_count": 0}
    assert validation == {"schema_version": "1.0", "status": "passed", "issues": []}
    assert "output_tail" not in release_gate_text
    assert "diagnostic_tail" not in release_gate_text
    assert release_gate_report["commands"] == [{"name": "browser_smoke", "returncode": 0, "cwd": "."}]
    assert_public_safe(manifest_text)
    assert_public_safe(handoff)
    assert_public_safe(release_gate_text)


def test_rc_pilot_failed_gate_writes_failed_manifest_without_sensitive_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "rc-failed"
    manifest = run_rc_pilot(output_dir=output_dir, runner=_failing_release_gate_runner)
    manifest_text = (output_dir / "rc_manifest.json").read_text(encoding="utf-8")
    handoff = (output_dir / "rc_handoff.md").read_text(encoding="utf-8")

    assert manifest["status"] == "failed"
    assert manifest["release_gate"]["status"] == "failed"
    assert manifest["redaction"]["status"] == "passed"
    assert_public_safe(manifest_text)
    assert_public_safe(handoff)


def test_rc_pilot_optional_review_packet_failure_is_safe_and_non_crashing(tmp_path: Path) -> None:
    output_dir = tmp_path / "rc-review"
    manifest = run_rc_pilot(output_dir=output_dir, review_job_id="missing-job", runner=_review_packet_unavailable_runner)
    rendered = json.dumps(manifest, ensure_ascii=False)

    assert manifest["status"] == "passed"
    assert manifest["review_packet"]["status"] == "skipped_or_unavailable"
    assert manifest["review_packet"]["reason"] == "[redacted]"
    assert_public_safe(rendered)


def test_rc_handoff_validator_rejects_unsafe_or_incomplete_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "rc_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "passed",
                "checked_at": "2026-07-07T00:00:00+00:00",
                "redaction": {"status": "failed", "unsafe_tokens": ["/Users/"]},
                "true_ai_opt_in": {"status": "skipped_opt_in", "required": True},
                "output_location": {"status": "repo_external", "ref": "rc"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "rc_handoff.md").write_text("Traceback at /tmp/private", encoding="utf-8")

    report = check_rc_handoff(manifest_path)

    assert report["status"] == "failed"
    messages = " ".join(issue["message"] for issue in report["issues"])
    assert "required field missing" in messages
    assert "redaction must be passed" in messages
    assert "true-AI skipped opt-in must not be required" in messages


def test_rc_handoff_validator_checks_generated_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "rc-artifacts"
    run_rc_pilot(output_dir=output_dir, runner=_passing_runner)
    (output_dir / "release_gate_report.json").write_text(
        json.dumps({"schema_version": "1.0", "status": "passed", "commands": [{"output_tail": ["safe line"]}]}),
        encoding="utf-8",
    )
    (output_dir / "release_evidence" / "evidence.json").write_text(
        json.dumps({"schema_version": "1.0", "status": "passed", "note": "Traceback at /tmp/private"}),
        encoding="utf-8",
    )
    (output_dir / "release_evidence" / "evidence.md").write_text("raw command leaked", encoding="utf-8")

    report = check_rc_handoff(output_dir / "rc_manifest.json")

    assert report["status"] == "failed"
    messages = " ".join(issue["message"] for issue in report["issues"])
    assert "release gate report must not contain output_tail or diagnostic_tail" in messages
    assert "generated artifact contains unsafe token" in messages


def test_rc_handoff_validator_rejects_malformed_true_ai_status(tmp_path: Path) -> None:
    output_dir = tmp_path / "rc-true-ai"
    run_rc_pilot(output_dir=output_dir, runner=_passing_runner)
    manifest_path = output_dir / "rc_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["true_ai_opt_in"] = {"status": "not_run"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check_rc_handoff(manifest_path)

    assert report["status"] == "failed"
    assert any(issue["field"] == "true_ai_opt_in" for issue in report["issues"])


def test_rc_pilot_redaction_failure_writes_minimal_safe_failed_bundle(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "rc-redaction"
    original_build_manifest = rc_pilot._build_manifest

    def unsafe_manifest(**kwargs):
        manifest = original_build_manifest(**kwargs)
        manifest["unsafe"] = "Traceback at /tmp/private"
        return manifest

    monkeypatch.setattr(rc_pilot, "_build_manifest", unsafe_manifest)

    manifest = rc_pilot.run_rc_pilot(output_dir=output_dir, runner=_passing_runner)
    manifest_text = (output_dir / "rc_manifest.json").read_text(encoding="utf-8")
    handoff = (output_dir / "rc_handoff.md").read_text(encoding="utf-8")

    assert manifest["status"] == "failed"
    assert manifest["redaction"]["status"] == "failed"
    assert (output_dir / "rc_manifest.json").exists()
    assert (output_dir / "rc_handoff.md").exists()
    assert_public_safe(manifest_text)
    assert_public_safe(handoff)


def _passing_runner(command: RcCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "local_setup":
        return subprocess.CompletedProcess(
            command.command,
            0,
            stdout=json.dumps({"schema_version": "1.0", "status": "passed", "redaction": {"status": "passed", "unsafe_tokens": []}}),
            stderr="",
        )
    if command.name == "release_gate":
        return subprocess.CompletedProcess(command.command, 0, stdout=json.dumps(_gate_report("passed")), stderr="")
    if command.name == "release_evidence":
        output_dir = Path(command.command[command.command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence.json").write_text(json.dumps(_evidence_report("passed")), encoding="utf-8")
        (output_dir / "evidence.md").write_text("# evidence\n", encoding="utf-8")
    if command.name == "git_status":
        return subprocess.CompletedProcess(command.command, 0, stdout="## codex/v1-rc-pilot-handoff\n", stderr="")
    return subprocess.CompletedProcess(command.command, 0, stdout="{}", stderr="")


def _failing_release_gate_runner(command: RcCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "release_gate":
        return subprocess.CompletedProcess(command.command, 1, stdout=json.dumps(_gate_report("failed")), stderr="stderr leaked")
    return _passing_runner(command)


def _review_packet_unavailable_runner(command: RcCommand) -> subprocess.CompletedProcess[str]:
    if command.name == "review_packet_export":
        return subprocess.CompletedProcess(
            command.command,
            1,
            stdout=json.dumps({"schema_version": "1.0", "status": "failed", "error": "Traceback at /tmp/private"}),
            stderr="",
        )
    return _passing_runner(command)


def _gate_report(status: str) -> dict:
    return {
        "schema_version": "1.0",
        "status": status,
        "checked_at": "2026-07-07T00:00:00+00:00",
        "commands": [
            {
                "name": "browser_smoke",
                "returncode": 0,
                "cwd": ".",
                "output_tail": ["safe output that must not enter RC bundle"],
                "diagnostic_tail": ["safe diagnostic that must not enter RC bundle"],
            }
        ],
        "artifact_hygiene": {"status": "passed", "branch": "## codex/v1-rc-pilot-handoff", "forbidden_status_entries": [], "generated_artifacts_present": []},
        "redaction": {"status": "passed", "unsafe_tokens": []},
        "local_setup": {"status": "passed", "returncode": 0},
        "manual_eval": {"status": "passed", "returncode": 0},
        "browser_smoke": {"status": "passed", "returncode": 0},
        "cleanup": {"status": "passed", "returncode": 0},
        "true_ai_opt_in": {"status": "skipped_opt_in"},
    }


def _evidence_report(status: str) -> dict:
    return {
        "schema_version": "1.0",
        "status": status,
        "checked_at": "2026-07-07T00:00:00+00:00",
    }


def assert_public_safe(payload: str) -> None:
    for token in UNSAFE_TOKENS:
        assert token not in payload
