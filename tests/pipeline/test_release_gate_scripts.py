from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from scripts.check_manual_eval_gate import check_manual_eval_gate
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
