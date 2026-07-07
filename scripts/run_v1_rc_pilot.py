from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Any

try:
    from scripts.redaction import find_unsafe_tokens
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-v1-rc-pilot")
MANIFEST_FILENAME = "rc_manifest.json"
HANDOFF_FILENAME = "rc_handoff.md"


@dataclass(frozen=True)
class RcCommand:
    name: str
    command: list[str]
    cwd: Path = REPO_ROOT
    optional: bool = False


CommandRunner = Callable[[RcCommand], subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GrooveScribe V1 release candidate pilot handoff.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--include-true-ai", action="store_true", help="Opt in to true-AI gate checks.")
    parser.add_argument("--review-job-id", help="Optional completed job to export into the handoff bundle.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if _inside_repo(args.output_dir):
        print(_failure_json("output_dir_must_be_outside_repo"))
        return 2
    manifest = run_rc_pilot(
        output_dir=args.output_dir,
        include_true_ai=args.include_true_ai,
        review_job_id=args.review_job_id,
    )
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": manifest["status"],
                "manifest": MANIFEST_FILENAME,
                "handoff": HANDOFF_FILENAME,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if manifest["status"] == "passed" else 1


def run_rc_pilot(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    include_true_ai: bool = False,
    review_job_id: str | None = None,
    runner: CommandRunner | None = None,
) -> dict:
    if _inside_repo(output_dir):
        raise ValueError("output_dir_must_be_outside_repo")

    command_runner = runner or _run_command
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    release_evidence_dir = output_dir / "release_evidence"
    release_gate_report_path = output_dir / "release_gate_report.json"

    commands: list[dict[str, Any]] = []
    started_at = datetime.now(UTC).isoformat()

    local_setup = _run_json_command(
        RcCommand(
            "local_setup",
            [
                sys.executable,
                "scripts/check_v1_local_setup.py",
                "--skip-port-check",
            ],
        ),
        command_runner,
        commands,
        None,
    )
    release_gate = _run_json_command(
        RcCommand(
            "release_gate",
            [
                ".venv-ai/bin/python",
                "scripts/run_v1_release_gate.py",
                *(["--include-true-ai"] if include_true_ai else []),
            ],
        ),
        command_runner,
        commands,
        None,
    )
    _write_json_file(release_gate_report_path, _release_gate_bundle_report(release_gate))
    release_evidence = _run_evidence_command(
        release_gate_report_path=release_gate_report_path,
        output_dir=release_evidence_dir,
        runner=command_runner,
        commands=commands,
    )
    git_status = _run_text_command(RcCommand("git_status", ["git", "status", "--short", "--branch"]), command_runner, commands)
    git_diff = _run_text_command(RcCommand("git_diff_check", ["git", "diff", "--check"]), command_runner, commands)
    review_packet = _export_review_packet(
        review_job_id=review_job_id,
        output_dir=output_dir,
        runner=command_runner,
        commands=commands,
    )

    manifest = _build_manifest(
        checked_at=started_at,
        commands=commands,
        local_setup=local_setup,
        release_gate=release_gate,
        release_evidence=release_evidence,
        git_status=git_status,
        git_diff=git_diff,
        review_packet=review_packet,
        output_dir=output_dir,
    )
    _finalize_redaction(manifest)
    if manifest["redaction"]["status"] != "passed":
        manifest = _minimal_failed_manifest(checked_at=started_at, reason="redaction_failed")
    handoff = render_handoff_markdown(manifest)
    _assert_public_safe(manifest)
    _assert_public_safe(handoff)

    (output_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / HANDOFF_FILENAME).write_text(handoff + "\n", encoding="utf-8")
    return manifest


def _minimal_failed_manifest(*, checked_at: str, reason: str) -> dict:
    return {
        "schema_version": "1.0",
        "status": "failed",
        "checked_at": checked_at,
        "output_location": {"status": "repo_external", "ref": "redacted"},
        "git": {"branch": "", "status_check": {"status": "unknown"}, "diff_check": {"status": "unknown"}},
        "commands": [],
        "local_setup": {"status": "unknown"},
        "release_gate": {"status": "unknown"},
        "release_evidence": {"status": "unknown"},
        "artifact_hygiene": {"status": "unknown"},
        "manual_eval": {"status": "unknown"},
        "browser_smoke": {"status": "unknown"},
        "review_packet": {"status": "unknown"},
        "true_ai_opt_in": {"status": "skipped_opt_in"},
        "generated_outputs": [MANIFEST_FILENAME, HANDOFF_FILENAME],
        "redaction": {"status": "failed", "unsafe_token_count": 1, "reason": _safe_text(reason)},
    }


def render_handoff_markdown(manifest: dict) -> str:
    lines = [
        "# GrooveScribe V1 RC Handoff",
        "",
        f"- Status: `{manifest.get('status')}`",
        f"- Checked at: `{manifest.get('checked_at')}`",
        f"- Branch: `{manifest.get('git', {}).get('branch', '')}`",
        "",
        "## Gate Summary",
        "",
        f"- Local setup: `{manifest['local_setup'].get('status')}`",
        f"- Release gate: `{manifest['release_gate'].get('status')}`",
        f"- Release evidence: `{manifest['release_evidence'].get('status')}`",
        f"- Browser smoke: `{manifest['browser_smoke'].get('status')}`",
        f"- Manual eval: `{manifest['manual_eval'].get('status')}`",
        f"- Artifact hygiene: `{manifest['artifact_hygiene'].get('status')}`",
        f"- Redaction: `{manifest['redaction'].get('status')}`",
        f"- True-AI: `{manifest['true_ai_opt_in'].get('status')}`",
        f"- Review packet: `{manifest['review_packet'].get('status')}`",
        "",
        "## Generated Files",
        "",
        "- `rc_manifest.json`",
        "- `rc_handoff.md`",
        "- `release_gate_report.json`",
        "- `release_evidence/evidence.json`",
        "- `release_evidence/evidence.md`",
        "",
        "## Reviewer Checklist",
        "",
        "- Confirm release gate and release evidence are passed.",
        "- Confirm browser smoke covers desktop and mobile result review.",
        "- Confirm manual eval gate is passed and true-AI remains opt-in unless explicitly requested.",
        "- Confirm PDF renderer remains optional and does not block MIDI/MusicXML handoff.",
        "- Confirm generated RC outputs, review packets, storage, DB, build outputs, and Playwright reports are not committed.",
    ]
    rendered = "\n".join(lines)
    _assert_public_safe(rendered)
    return rendered


def _run_json_command(
    command: RcCommand,
    runner: CommandRunner,
    commands: list[dict[str, Any]],
    output_path: Path | None,
) -> dict:
    result = runner(command)
    commands.append(_command_report(command, result))
    if output_path is not None and output_path.exists():
        payload = _load_json_file(output_path)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    parsed = _parse_json_stdout(result.stdout)
    if parsed is not None:
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return parsed
    return {"status": "failed" if result.returncode else "unknown", "returncode": result.returncode}


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_evidence_command(
    *,
    release_gate_report_path: Path,
    output_dir: Path,
    runner: CommandRunner,
    commands: list[dict[str, Any]],
) -> dict:
    command = RcCommand(
        "release_evidence",
        [
            ".venv-ai/bin/python",
            "scripts/generate_v1_release_evidence.py",
            "--gate-report",
            release_gate_report_path.as_posix(),
            "--output-dir",
            output_dir.as_posix(),
        ],
    )
    result = runner(command)
    commands.append(_command_report(command, result))
    evidence_path = output_dir / "evidence.json"
    if evidence_path.exists():
        payload = _load_json_file(evidence_path)
        evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path = output_dir / "evidence.md"
        if markdown_path.exists() and find_unsafe_tokens(markdown_path.read_text(encoding="utf-8")):
            markdown_path.write_text("# GrooveScribe V1 Release Evidence\n\n- Status: `redacted_due_unsafe_payload`\n", encoding="utf-8")
        return payload
    parsed = _parse_json_stdout(result.stdout)
    if parsed is not None:
        return parsed
    return {"status": "failed" if result.returncode else "unknown", "returncode": result.returncode}


def _run_text_command(command: RcCommand, runner: CommandRunner, commands: list[dict[str, Any]]) -> dict:
    result = runner(command)
    commands.append(_command_report(command, result))
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "lines": [_safe_line(line) for line in result.stdout.splitlines() if line.strip()],
    }


def _export_review_packet(
    *,
    review_job_id: str | None,
    output_dir: Path,
    runner: CommandRunner,
    commands: list[dict[str, Any]],
) -> dict:
    if not review_job_id:
        return {"status": "capability_available", "enabled": False, "files": []}
    packet_dir = output_dir / "review_packet"
    command = RcCommand(
        "review_packet_export",
        [
            "backend/.venv/bin/python",
            "scripts/export_review_packet.py",
            "--job-id",
            review_job_id,
            "--output-dir",
            packet_dir.as_posix(),
            "--zip",
        ],
        optional=True,
    )
    result = runner(command)
    commands.append(_command_report(command, result))
    if result.returncode != 0:
        return {
            "status": "skipped_or_unavailable",
            "enabled": True,
            "returncode": result.returncode,
            "reason": _safe_error_from_stdout(result.stdout),
            "files": [],
        }
    return {
        "status": "exported",
        "enabled": True,
        "returncode": result.returncode,
        "files": ["review_packet.json", "review_notes.md", "review_packet.zip"],
    }


def _build_manifest(
    *,
    checked_at: str,
    commands: list[dict[str, Any]],
    local_setup: dict,
    release_gate: dict,
    release_evidence: dict,
    git_status: dict,
    git_diff: dict,
    review_packet: dict,
    output_dir: Path,
) -> dict:
    artifact_hygiene = _safe_artifact_hygiene(release_gate.get("artifact_hygiene", {}))
    manifest = {
        "schema_version": "1.0",
        "status": "passed",
        "checked_at": checked_at,
        "output_location": {"status": "repo_external", "ref": _safe_text(output_dir.name)},
        "git": {
            "branch": _branch_from_git_status(git_status),
            "status_check": _summarize_status(git_status),
            "diff_check": _summarize_status(git_diff),
        },
        "commands": commands,
        "local_setup": _summarize_status(local_setup),
        "release_gate": _summarize_release_gate(release_gate),
        "release_evidence": _summarize_release_evidence(release_evidence),
        "artifact_hygiene": artifact_hygiene,
        "manual_eval": _summarize_status(release_gate.get("manual_eval", release_evidence.get("manual_eval", {}))),
        "browser_smoke": _summarize_status(release_gate.get("browser_smoke", release_evidence.get("browser_smoke", {}))),
        "review_packet": review_packet,
        "true_ai_opt_in": _summarize_status(release_gate.get("true_ai_opt_in", release_evidence.get("true_ai_opt_in", {}))),
        "generated_outputs": [
            MANIFEST_FILENAME,
            HANDOFF_FILENAME,
            "release_gate_report.json",
            "release_evidence/evidence.json",
            "release_evidence/evidence.md",
        ],
    }
    manifest["status"] = _overall_status(manifest)
    return manifest


def _overall_status(manifest: dict) -> str:
    required = [
        manifest["git"]["status_check"].get("status") == "passed",
        manifest["git"]["diff_check"].get("status") == "passed",
        manifest["local_setup"].get("status") in {"passed", "warning"},
        manifest["release_gate"].get("status") == "passed",
        manifest["release_evidence"].get("status") == "passed",
        manifest["artifact_hygiene"].get("status") == "passed",
        manifest["manual_eval"].get("status") == "passed",
        manifest["browser_smoke"].get("status") == "passed",
    ]
    return "passed" if all(required) else "failed"


def _finalize_redaction(manifest: dict) -> None:
    manifest["redaction"] = {"status": "pending", "unsafe_token_count": 0}
    unsafe = find_unsafe_tokens(json.dumps(manifest, ensure_ascii=False))
    manifest["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        manifest["status"] = "failed"


def _summarize_release_gate(gate: dict) -> dict:
    return {
        "schema_version": _safe_text(gate.get("schema_version")),
        "status": _safe_text(gate.get("status", "unknown")),
        "checked_at": _safe_text(gate.get("checked_at")),
        "command_count": len(gate.get("commands", [])) if isinstance(gate.get("commands"), list) else 0,
    }


def _release_gate_bundle_report(gate: dict) -> dict:
    return {
        "schema_version": _safe_text(gate.get("schema_version")),
        "status": _safe_text(gate.get("status", "unknown")),
        "checked_at": _safe_text(gate.get("checked_at")),
        "commands": [
            {
                "name": _safe_text(command.get("name")),
                "returncode": command.get("returncode"),
                "cwd": _safe_text(command.get("cwd")),
            }
            for command in gate.get("commands", [])
            if isinstance(command, dict)
        ],
        "artifact_hygiene": _safe_artifact_hygiene(gate.get("artifact_hygiene", {})),
        "redaction": _redaction_summary(gate.get("redaction", {})),
        "local_setup": _summarize_status(gate.get("local_setup", {})),
        "manual_eval": _summarize_status(gate.get("manual_eval", {})),
        "browser_smoke": _summarize_status(gate.get("browser_smoke", {})),
        "cleanup": _summarize_status(gate.get("cleanup", {})),
        "true_ai_opt_in": _summarize_true_ai(gate.get("true_ai_opt_in", {})),
    }


def _redaction_summary(summary: dict) -> dict:
    unsafe_tokens = summary.get("unsafe_tokens")
    return {
        "status": _safe_text(summary.get("status", "unknown")),
        "unsafe_token_count": len(unsafe_tokens) if isinstance(unsafe_tokens, list) else 0,
    }


def _summarize_true_ai(summary: dict) -> dict:
    status = _safe_text(summary.get("status", "unknown"))
    result = {"status": status}
    commands = summary.get("commands")
    if isinstance(commands, list):
        result["commands"] = [
            {
                "name": _safe_text(command.get("name")),
                "returncode": command.get("returncode"),
                "cwd": _safe_text(command.get("cwd")),
            }
            for command in commands
            if isinstance(command, dict)
        ]
    return result


def _summarize_release_evidence(evidence: dict) -> dict:
    return {
        "schema_version": _safe_text(evidence.get("schema_version")),
        "status": _safe_text(evidence.get("status", "unknown")),
        "checked_at": _safe_text(evidence.get("checked_at")),
    }


def _safe_artifact_hygiene(hygiene: dict) -> dict:
    return {
        "status": _safe_text(hygiene.get("status", "unknown")),
        "branch": _safe_text(hygiene.get("branch", "")),
        "forbidden_status_entries": [_safe_text(item) for item in hygiene.get("forbidden_status_entries", [])],
        "generated_artifacts_present": [_safe_text(item) for item in hygiene.get("generated_artifacts_present", [])],
    }


def _summarize_status(summary: dict) -> dict:
    result = {"status": _safe_text(summary.get("status", "unknown"))}
    if "returncode" in summary:
        result["returncode"] = summary.get("returncode")
    return result


def _branch_from_git_status(git_status: dict) -> str:
    for line in git_status.get("lines", []):
        if isinstance(line, str) and line.startswith("## "):
            return _safe_text(line)
    return ""


def _command_report(command: RcCommand, result: subprocess.CompletedProcess[str]) -> dict:
    return {
        "name": command.name,
        "command": _safe_command(command.command),
        "cwd": _relative_cwd(command.cwd),
        "returncode": result.returncode,
        "optional": command.optional,
    }


def _run_command(command: RcCommand) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command.command, cwd=command.cwd, capture_output=True, text=True, check=False)


def _load_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "failed", "reason": "json_unavailable"}
    return _sanitize_object(payload)


def _parse_json_stdout(stdout: str) -> dict | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return _sanitize_object(payload) if isinstance(payload, dict) else None


def _sanitize_object(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _safe_key(key)
            if safe_key is None or safe_key in sanitized:
                continue
            sanitized[safe_key] = _sanitize_object(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_object(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _safe_key(value: object) -> str | None:
    text = str(value)
    if find_unsafe_tokens(text):
        return None
    return text


def _safe_text(value: object) -> str:
    text = "" if value is None else str(value)
    return "[redacted]" if find_unsafe_tokens(text) else text


def _safe_line(value: str) -> str:
    return "[redacted]" if find_unsafe_tokens(value) else value


def _safe_command(command: list[str]) -> str:
    return " ".join(_safe_command_part(part) for part in command)


def _safe_command_part(value: str) -> str:
    if find_unsafe_tokens(value):
        path = Path(value)
        return path.name if path.name else "[redacted]"
    return value


def _safe_error_from_stdout(stdout: str) -> str:
    parsed = _parse_json_stdout(stdout)
    if isinstance(parsed, dict):
        error = parsed.get("error") or parsed.get("status")
        if error:
            return _safe_text(error)
    return "review_packet_unavailable"


def _relative_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix() or "."
    except ValueError:
        return path.name


def _inside_repo(path: Path) -> bool:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    try:
        resolved.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def _assert_public_safe(payload: object) -> None:
    if find_unsafe_tokens(json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload):
        raise ValueError("unsafe_rc_handoff_payload")


def _failure_json(error: str) -> str:
    return json.dumps({"schema_version": "1.0", "status": "failed", "error": _safe_text(error)}, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
