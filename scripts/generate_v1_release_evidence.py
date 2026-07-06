from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.check_manual_eval_gate import check_manual_eval_gate
    from scripts.cleanup_storage import inspect_storage
    from scripts.plan_local_reset import plan_local_reset
    from scripts.redaction import find_unsafe_tokens
    from scripts.run_v1_release_gate import check_artifact_hygiene, run_gate
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from check_manual_eval_gate import check_manual_eval_gate
    from cleanup_storage import inspect_storage
    from plan_local_reset import plan_local_reset
    from redaction import find_unsafe_tokens
    from run_v1_release_gate import check_artifact_hygiene, run_gate

DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-v1-release-evidence")
DEFAULT_MANUAL_EVAL_DIR = Path("tests/manual_eval")
DEFAULT_STORAGE_ROOT = Path("storage/local")
DEFAULT_DATABASE = Path("storage/local/groovescribe.db")
DEFAULT_TEMPLATE = Path("tests/manual_eval/manual_eval_template.csv")
SCORE_FIELDS = (
    "kick_score",
    "snare_score",
    "hihat_score",
    "timing_score",
    "notation_readability_score",
    "overall_usability_score",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate redacted V1 release evidence outside the repo.")
    parser.add_argument("--gate-report", type=Path, help="Existing run_v1_release_gate.py JSON report to summarize.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--include-true-ai", action="store_true", help="Opt in to true-AI tests when running the gate.")
    parser.add_argument("--manual-eval-dir", type=Path, default=DEFAULT_MANUAL_EVAL_DIR)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = build_release_evidence(
        gate_report_path=args.gate_report,
        include_true_ai=args.include_true_ai,
        manual_eval_dir=args.manual_eval_dir,
        storage_root=args.storage_root,
        database=args.database,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "evidence.json"
    markdown_path = args.output_dir / "evidence.md"
    json_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(evidence) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": evidence["status"],
                "json_path": _safe_path_ref(json_path),
                "markdown_path": _safe_path_ref(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if evidence["status"] == "passed" else 1


def build_release_evidence(
    *,
    gate_report_path: Path | None = None,
    include_true_ai: bool = False,
    manual_eval_dir: Path = DEFAULT_MANUAL_EVAL_DIR,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    database: Path = DEFAULT_DATABASE,
    gate_report: dict | None = None,
) -> dict:
    started_at = datetime.now(UTC).isoformat()
    gate = gate_report or _load_or_run_gate(gate_report_path, include_true_ai=include_true_ai)
    manual_eval = summarize_manual_eval(manual_eval_dir)
    cleanup = inspect_storage(storage_root, database)
    reset = plan_local_reset(storage_root, database)
    hygiene = check_artifact_hygiene()
    runtime = summarize_runtime_readiness(gate)
    evidence = {
        "schema_version": "1.0",
        "status": "passed",
        "checked_at": started_at,
        "git_hygiene": safe_artifact_hygiene(hygiene),
        "release_gate": summarize_release_gate(gate),
        "runtime_readiness": runtime,
        "manual_eval": manual_eval,
        "browser_smoke": summarize_command_status(gate.get("browser_smoke", {"status": "not_run"})),
        "cleanup_reset": {
            "cleanup": _safe_cleanup_summary(cleanup),
            "reset": _safe_reset_summary(reset),
        },
        "artifact_hygiene": safe_artifact_hygiene(hygiene),
        "true_ai_opt_in": summarize_true_ai(gate.get("true_ai_opt_in", {"status": "skipped_opt_in"})),
    }
    redaction = redaction_summary(evidence)
    evidence["redaction"] = redaction
    evidence["status"] = _overall_status(evidence)
    return evidence


def summarize_release_gate(gate: dict) -> dict:
    return {
        "schema_version": _safe_text(gate.get("schema_version")),
        "status": _safe_text(gate.get("status", "unknown")),
        "checked_at": _safe_text(gate.get("checked_at")),
        "commands": [
            {
                "name": _safe_text(command.get("name")),
                "returncode": command.get("returncode"),
                "cwd": _safe_path_ref(Path(str(command.get("cwd")))) if command.get("cwd") is not None else None,
            }
            for command in gate.get("commands", [])
        ],
        "manual_eval": summarize_command_status(gate.get("manual_eval", {"status": "not_run"})),
        "browser_smoke": summarize_command_status(gate.get("browser_smoke", {"status": "not_run"})),
        "cleanup": summarize_command_status(gate.get("cleanup", {"status": "not_run"})),
        "redaction": summarize_redaction_status(gate.get("redaction", {"status": "not_run"})),
    }


def summarize_runtime_readiness(gate: dict) -> dict:
    backend_targeted = _command_by_name(gate, "backend_targeted")
    return {
        "status": "passed" if backend_targeted.get("returncode") == 0 else "failed",
        "covered_by": "backend_targeted",
        "contract": "GET /api/v1/runtime/preflight",
        "allowed_statuses": ["ready", "degraded", "not_ready", "error"],
        "mock_upload_gate": "mock_ai_ready=true",
        "true_ai_policy": "opt_in",
        "details": {
            "command": backend_targeted.get("name", "backend_targeted"),
            "returncode": backend_targeted.get("returncode"),
        },
    }


def summarize_true_ai(true_ai: dict) -> dict:
    summary = {"status": _safe_text(true_ai.get("status", "unknown"))}
    commands = true_ai.get("commands")
    if isinstance(commands, list):
        summary["commands"] = [
            {
                "name": _safe_text(command.get("name")),
                "returncode": command.get("returncode"),
                "cwd": _safe_path_ref(Path(str(command.get("cwd")))) if command.get("cwd") is not None else None,
            }
            for command in commands
        ]
    return summary


def summarize_command_status(summary: dict) -> dict:
    result = {"status": _safe_text(summary.get("status", "unknown"))}
    if "returncode" in summary:
        result["returncode"] = summary.get("returncode")
    return result


def summarize_redaction_status(summary: dict) -> dict:
    return {
        "status": _safe_text(summary.get("status", "unknown")),
        "unsafe_token_count": len(summary.get("unsafe_tokens", [])) if isinstance(summary.get("unsafe_tokens"), list) else 0,
    }


def safe_artifact_hygiene(hygiene: dict) -> dict:
    return {
        "status": _safe_text(hygiene.get("status", "unknown")),
        "branch": _safe_text(hygiene.get("branch", "")),
        "forbidden_status_entries": [_safe_text(item) for item in hygiene.get("forbidden_status_entries", [])],
        "generated_artifacts_present": [_safe_text(item) for item in hygiene.get("generated_artifacts_present", [])],
    }


def summarize_manual_eval(manual_eval_dir: Path) -> dict:
    gate = check_manual_eval_gate(manual_eval_dir)
    rows = _read_manual_eval_rows(manual_eval_dir)
    blocked = [row for row in rows if row.get("blocked_reason", "").strip()]
    completed = [row for row in rows if not row.get("blocked_reason", "").strip()]
    latest_true_ai = _latest_true_ai_row(rows)
    return {
        "status": gate["status"],
        "checked_files": gate["checked_files"],
        "checked_rows": gate["checked_rows"],
        "completed_rows": len(completed),
        "blocked_rows": len(blocked),
        "latest_true_ai": latest_true_ai,
        "issues": [_safe_issue(issue) for issue in gate["issues"]],
    }


def redaction_summary(payload: object) -> dict:
    unsafe = find_unsafe_tokens(json.dumps(payload, ensure_ascii=False))
    return {
        "status": "passed" if not unsafe else "failed",
        "unsafe_tokens": unsafe,
    }


def render_markdown(evidence: dict) -> str:
    latest_true_ai = evidence["manual_eval"].get("latest_true_ai") or {}
    lines = [
        "# GrooveScribe V1 Release Evidence",
        "",
        f"- Status: `{evidence['status']}`",
        f"- Checked at: `{evidence['checked_at']}`",
        f"- Branch: `{evidence['git_hygiene'].get('branch', '')}`",
        "",
        "## Gate Summary",
        "",
        f"- Release gate: `{evidence['release_gate'].get('status')}`",
        f"- Runtime readiness: `{evidence['runtime_readiness'].get('status')}`",
        f"- Browser smoke: `{evidence['browser_smoke'].get('status')}`",
        f"- Manual eval: `{evidence['manual_eval'].get('status')}`",
        f"- Cleanup dry-run: `{evidence['cleanup_reset']['cleanup'].get('status')}`",
        f"- Reset plan: `{evidence['cleanup_reset']['reset'].get('status')}`",
        f"- True-AI: `{evidence['true_ai_opt_in'].get('status')}`",
        f"- Redaction: `{evidence['redaction'].get('status')}`",
        "",
        "## Manual Evaluation",
        "",
        f"- Checked rows: `{evidence['manual_eval'].get('checked_rows')}`",
        f"- Completed rows: `{evidence['manual_eval'].get('completed_rows')}`",
        f"- Blocked rows: `{evidence['manual_eval'].get('blocked_rows')}`",
        f"- Latest true-AI ref: `{latest_true_ai.get('baseline_report_ref', 'none')}`",
        "",
        "## Local Data",
        "",
        f"- Storage root: `{evidence['cleanup_reset']['cleanup'].get('storage_root_name')}`",
        f"- Job dirs: `{evidence['cleanup_reset']['cleanup'].get('job_dir_count')}`",
        f"- DB status: `{evidence['cleanup_reset']['cleanup'].get('database_status')}`",
        f"- Reset execute supported: `{evidence['cleanup_reset']['reset'].get('execute_supported')}`",
        "",
        "## Notes",
        "",
        "- true-AI remains opt-in and is not a deterministic release blocker.",
        "- PDF renderer availability is optional for V1 and does not block MIDI/MusicXML.",
        "- Evidence files are generated outside the repo and must not be committed.",
    ]
    rendered = "\n".join(lines)
    unsafe = find_unsafe_tokens(rendered)
    if unsafe:
        raise ValueError(f"unsafe evidence markdown tokens: {', '.join(unsafe)}")
    return rendered


def _overall_status(evidence: dict) -> str:
    checks = [
        evidence["git_hygiene"].get("status") == "passed",
        evidence["release_gate"].get("status") == "passed",
        evidence["runtime_readiness"].get("status") == "passed",
        evidence["manual_eval"].get("status") == "passed",
        evidence["browser_smoke"].get("status") == "passed",
        evidence["cleanup_reset"]["cleanup"].get("status") == "dry_run",
        evidence["cleanup_reset"]["reset"].get("status") == "dry_run",
        evidence["cleanup_reset"]["cleanup"].get("execute_supported") is False,
        evidence["cleanup_reset"]["reset"].get("execute_supported") is False,
        evidence["artifact_hygiene"].get("status") == "passed",
        evidence["redaction"].get("status") == "passed",
    ]
    return "passed" if all(checks) else "failed"


def _load_or_run_gate(gate_report_path: Path | None, *, include_true_ai: bool) -> dict:
    if gate_report_path:
        return json.loads(gate_report_path.read_text(encoding="utf-8"))
    return run_gate(include_true_ai=include_true_ai)


def _command_by_name(gate: dict, name: str) -> dict:
    for command in gate.get("commands", []):
        if command.get("name") == name:
            return command
    return {}


def _read_manual_eval_rows(manual_eval_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(manual_eval_dir.glob("*.csv")):
        if path.name == DEFAULT_TEMPLATE.name:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows.extend(row for row in reader if any(value.strip() for value in row.values()))
    return rows


def _latest_true_ai_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    true_ai_rows = [row for row in rows if row.get("runtime_mode") == "true_ai"]
    if not true_ai_rows:
        return None
    row = sorted(true_ai_rows, key=lambda item: item.get("date", ""))[-1]
    return {
        "date": row.get("date", ""),
        "fixture_name": row.get("fixture_name", ""),
        "runtime_mode": row.get("runtime_mode", ""),
        "baseline_report_ref": row.get("baseline_report_ref", ""),
        "artifact_ref": row.get("artifact_ref", ""),
        "blocked": bool(row.get("blocked_reason", "").strip()),
        "scored": any(row.get(field, "").strip() for field in SCORE_FIELDS),
    }


def _safe_cleanup_summary(cleanup: dict) -> dict:
    return {
        "status": cleanup.get("status"),
        "dry_run": cleanup.get("dry_run"),
        "execute_supported": cleanup.get("execute_supported"),
        "execute_refused": cleanup.get("execute_refused"),
        "storage_root_name": cleanup.get("storage_root_name"),
        "job_dir_count": cleanup.get("job_dir_count"),
        "database_found": cleanup.get("database_found"),
        "database_status": cleanup.get("database_status"),
        "database_job_count": cleanup.get("database_job_count"),
        "orphan_job_dir_count": len(cleanup.get("orphan_job_dirs", [])),
    }


def _safe_reset_summary(reset: dict) -> dict:
    return {
        "status": reset.get("status"),
        "dry_run": reset.get("dry_run"),
        "execute_supported": reset.get("execute_supported"),
        "execute_refused": reset.get("execute_refused"),
        "targets": reset.get("targets", {}),
        "would_delete": reset.get("would_delete", []),
    }


def _safe_issue(issue: dict) -> dict:
    return {
        "path": _safe_path_ref(Path(str(issue.get("path", "")))),
        "row_number": issue.get("row_number"),
        "field": _safe_text(issue.get("field", "")),
        "message": _safe_text(issue.get("message", "")),
    }


def _safe_path_ref(path: Path) -> str:
    text = path.as_posix()
    if path.is_absolute():
        return path.name
    return _safe_text(text)


def _safe_text(value: object) -> str:
    text = "" if value is None else str(value)
    return "[redacted]" if find_unsafe_tokens(text) else text


if __name__ == "__main__":
    raise SystemExit(main())
