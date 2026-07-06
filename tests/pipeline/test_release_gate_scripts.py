from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from scripts.check_manual_eval_gate import check_manual_eval_gate
from scripts.generate_v1_release_evidence import build_release_evidence, render_markdown
from scripts.plan_local_reset import plan_local_reset
from scripts.run_v1_release_gate import GateCommand, run_gate


def test_manual_eval_gate_passes_existing_repo_rows() -> None:
    report = check_manual_eval_gate(Path("tests/manual_eval"))

    assert report["status"] == "passed"
    assert report["checked_rows"] >= 1
    assert report["issues"] == []


def test_manual_eval_gate_rejects_schema_scores_and_sensitive_tokens(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual_eval"
    manual_dir.mkdir()
    template = Path("tests/manual_eval/manual_eval_template.csv")
    fields = next(csv.reader(template.open(encoding="utf-8")))
    (manual_dir / "manual_eval_template.csv").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    row = {field: "" for field in fields}
    row.update(
        {
            "date": "2026-07-03",
            "fixture_name": "fixture.wav",
            "runtime_mode": "true_ai",
            "pipeline_version": "local-first-v1",
            "baseline_report_ref": "baseline:test",
            "artifact_ref": "external:test",
            "kick_score": "1",
            "blocked_reason": "Traceback at /tmp/private/file.wav",
        }
    )
    with (manual_dir / "bad.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    report = check_manual_eval_gate(manual_dir, template_path=manual_dir / "manual_eval_template.csv")

    assert report["status"] == "failed"
    messages = " ".join(issue["message"] for issue in report["issues"])
    assert "blocked row must leave score field blank" in messages
    assert "unsafe diagnostic" in messages


def test_plan_local_reset_is_dry_run_only_and_uses_safe_refs(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    database = storage_root / "groovescribe.db"
    report = plan_local_reset(storage_root, database)

    assert report["status"] == "dry_run"
    assert report["execute_supported"] is False
    assert report["would_delete"] == []
    assert str(tmp_path) not in str(report)

    refused = plan_local_reset(storage_root, database, execute=True)
    assert refused["status"] == "refused"
    assert refused["execute_refused"] is True


def test_release_gate_report_is_redacted_and_marks_true_ai_opt_in_skipped() -> None:
    def fake_runner(step: GateCommand) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            step.command,
            0,
            stdout="passed\n/Users/private/path should be redacted\n",
            stderr="Traceback should be redacted\n",
        )

    report = run_gate(runner=fake_runner)

    assert report["status"] == "passed"
    assert report["schema_version"] == "1.0"
    assert report["manual_eval"]["status"] == "passed"
    assert report["browser_smoke"]["status"] == "passed"
    assert report["cleanup"]["status"] == "passed"
    assert report["true_ai_opt_in"]["status"] == "skipped_opt_in"
    assert report["redaction"]["status"] == "passed"
    assert "/Users/" not in str(report)
    assert "Traceback" not in str(report)
    assert "stdout" not in str(report).lower()
    assert "stderr" not in str(report).lower()


def test_release_evidence_summarizes_gate_manual_eval_and_cleanup_without_sensitive_tokens(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual_eval"
    manual_dir.mkdir()
    template = Path("tests/manual_eval/manual_eval_template.csv")
    fields = next(csv.reader(template.open(encoding="utf-8")))
    (manual_dir / "manual_eval_template.csv").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    completed = {field: "" for field in fields}
    completed.update(
        {
            "date": "2026-07-05",
            "fixture_name": "synthetic_clean_drum_pattern.wav",
            "runtime_mode": "true_ai",
            "pipeline_version": "local-first-v1",
            "runtime_version": "runtime:test",
            "baseline_report_ref": "baseline:20260705",
            "artifact_ref": "external:licensed-fixture",
            "kick_score": "3",
            "snare_score": "3",
            "hihat_score": "2",
            "timing_score": "3",
            "notation_readability_score": "3",
            "overall_usability_score": "3",
        }
    )
    blocked = {field: "" for field in fields}
    blocked.update(
        {
            "date": "2026-07-06",
            "fixture_name": "synthetic_clean_drum_pattern.wav",
            "runtime_mode": "true_ai",
            "pipeline_version": "local-first-v1",
            "runtime_version": "runtime:test",
            "baseline_report_ref": "baseline:20260706",
            "artifact_ref": "external:licensed-fixture",
            "blocked_reason": "adtof_verify_input_missing",
        }
    )
    with (manual_dir / "eval.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(completed)
        writer.writerow(blocked)

    storage_root = tmp_path / "storage"
    (storage_root / "jobs" / "orphan-job").mkdir(parents=True)
    gate_report = {
        "schema_version": "1.0",
        "status": "passed",
        "checked_at": "2026-07-06T00:00:00+00:00",
        "commands": [
            {
                "name": "backend_targeted",
                "returncode": 0,
                "cwd": "/Users/private/repo/backend",
                "output_tail": ["/Users/private"],
            },
            {"name": "browser_smoke", "returncode": 0, "cwd": ".", "output_tail": ["Traceback /tmp/private"]},
            {"name": "manual_eval_gate", "returncode": 0, "cwd": "."},
            {"name": "cleanup_dry_run", "returncode": 0, "cwd": "."},
        ],
        "manual_eval": {"status": "passed", "returncode": 0},
        "browser_smoke": {"status": "passed", "returncode": 0, "diagnostic_tail": ["stderr /var/folders/private"]},
        "cleanup": {"status": "passed", "returncode": 0, "output_tail": ["raw command leaked"]},
        "redaction": {"status": "passed", "unsafe_tokens": ["/Users/", "Traceback"]},
        "true_ai_opt_in": {
            "status": "blocked_or_failed",
            "commands": [
                {
                    "name": "pipeline_true_ai_opt_in",
                    "returncode": 1,
                    "cwd": "/private/tmp/true-ai-run",
                    "output_tail": ["Traceback /tmp/private"],
                }
            ],
        },
    }

    evidence = build_release_evidence(
        gate_report=gate_report,
        manual_eval_dir=manual_dir,
        storage_root=storage_root,
        database=storage_root / "groovescribe.db",
    )
    markdown = render_markdown(evidence)

    assert evidence["status"] == "passed"
    assert evidence["release_gate"]["status"] == "passed"
    assert evidence["runtime_readiness"]["status"] == "passed"
    assert evidence["manual_eval"]["completed_rows"] == 1
    assert evidence["manual_eval"]["blocked_rows"] == 1
    assert evidence["manual_eval"]["latest_true_ai"]["baseline_report_ref"] == "baseline:20260706"
    assert evidence["cleanup_reset"]["cleanup"]["status"] == "dry_run"
    assert evidence["cleanup_reset"]["reset"]["execute_supported"] is False
    assert evidence["true_ai_opt_in"] == {
        "status": "blocked_or_failed",
        "commands": [{"name": "pipeline_true_ai_opt_in", "returncode": 1, "cwd": "true-ai-run"}],
    }
    assert evidence["release_gate"]["commands"][0]["cwd"] == "backend"
    assert evidence["release_gate"]["redaction"] == {"status": "passed", "unsafe_token_count": 2}
    assert evidence["redaction"]["status"] == "passed"
    assert "/Users/" not in jsonish(evidence)
    assert "/tmp/" not in jsonish(evidence)
    assert "Traceback" not in jsonish(evidence)
    assert "command_template" not in jsonish(evidence)
    assert "/tmp/" not in markdown


def test_release_evidence_fails_when_required_gate_is_not_passed(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual_eval"
    manual_dir.mkdir()
    template = Path("tests/manual_eval/manual_eval_template.csv")
    (manual_dir / "manual_eval_template.csv").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    gate_report = {
        "schema_version": "1.0",
        "status": "failed",
        "checked_at": "2026-07-06T00:00:00+00:00",
        "commands": [{"name": "backend_targeted", "returncode": 1, "cwd": "backend"}],
        "manual_eval": {"status": "not_run"},
        "browser_smoke": {"status": "not_run"},
        "cleanup": {"status": "not_run"},
        "redaction": {"status": "passed", "unsafe_tokens": []},
        "true_ai_opt_in": {"status": "skipped_opt_in"},
    }

    evidence = build_release_evidence(
        gate_report=gate_report,
        manual_eval_dir=manual_dir,
        storage_root=tmp_path / "storage",
        database=tmp_path / "storage" / "groovescribe.db",
    )

    assert evidence["status"] == "failed"
    assert evidence["release_gate"]["status"] == "failed"
    assert evidence["runtime_readiness"]["status"] == "failed"


def test_release_evidence_cli_writes_redacted_files_from_gate_report(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual_eval"
    manual_dir.mkdir()
    template = Path("tests/manual_eval/manual_eval_template.csv")
    (manual_dir / "manual_eval_template.csv").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    gate_report = {
        "schema_version": "1.0",
        "status": "passed",
        "checked_at": "2026-07-06T00:00:00+00:00",
        "commands": [
            {
                "name": "backend_targeted",
                "returncode": 0,
                "cwd": "/Users/private/repo/backend",
                "output_tail": ["stdout Traceback /tmp/private"],
            }
        ],
        "manual_eval": {"status": "passed", "returncode": 0, "output_tail": ["command_template leaked"]},
        "browser_smoke": {"status": "passed", "returncode": 0},
        "cleanup": {"status": "passed", "returncode": 0},
        "redaction": {"status": "passed", "unsafe_tokens": ["/Users/", "stdout"]},
        "true_ai_opt_in": {"status": "skipped_opt_in"},
    }
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate_report), encoding="utf-8")
    output_dir = tmp_path / "evidence"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_v1_release_evidence.py",
            "--gate-report",
            str(gate_path),
            "--output-dir",
            str(output_dir),
            "--manual-eval-dir",
            str(manual_dir),
            "--storage-root",
            str(tmp_path / "storage"),
            "--database",
            str(tmp_path / "storage" / "groovescribe.db"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    evidence_json = (output_dir / "evidence.json").read_text(encoding="utf-8")
    evidence_md = (output_dir / "evidence.md").read_text(encoding="utf-8")
    assert "evidence.json" in result.stdout
    for payload in (result.stdout, evidence_json, evidence_md):
        assert "/Users/" not in payload
        assert "/tmp/" not in payload
        assert "Traceback" not in payload
        assert "stdout" not in payload.lower()
        assert "command_template" not in payload


def jsonish(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
