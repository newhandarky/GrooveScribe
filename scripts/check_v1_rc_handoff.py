from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.redaction import find_unsafe_tokens
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FIELDS = (
    "schema_version",
    "status",
    "checked_at",
    "git",
    "local_setup",
    "release_gate",
    "release_evidence",
    "artifact_hygiene",
    "redaction",
    "manual_eval",
    "browser_smoke",
    "review_packet",
    "true_ai_opt_in",
)
VALID_TOP_LEVEL_STATUSES = {"passed", "failed"}
VALID_TRUE_AI_STATUSES = {"skipped_opt_in", "passed", "blocked_or_failed"}
FORBIDDEN_RELEASE_GATE_KEYS = {"output_tail", "diagnostic_tail"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a redacted GrooveScribe V1 RC handoff bundle.")
    parser.add_argument("manifest", type=Path, nargs="?", help="Path to rc_manifest.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.manifest is None:
        parser = argparse.ArgumentParser(description="Validate a redacted GrooveScribe V1 RC handoff bundle.")
        parser.print_help()
        return 0
    report = check_rc_handoff(args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


def check_rc_handoff(manifest_path: Path) -> dict:
    issues: list[dict[str, str]] = []
    if _inside_repo(manifest_path):
        issues.append(_issue("manifest_path", "manifest must be outside the repo"))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1.0", "status": "failed", "issues": [_issue("manifest", "manifest unreadable")]}

    if not isinstance(manifest, dict):
        issues.append(_issue("manifest", "manifest must be a JSON object"))
        manifest = {}
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            issues.append(_issue(field, "required field missing"))
    if manifest.get("status") not in VALID_TOP_LEVEL_STATUSES:
        issues.append(_issue("status", "invalid status"))
    redaction = manifest.get("redaction") if isinstance(manifest.get("redaction"), dict) else {}
    if redaction.get("status") != "passed":
        issues.append(_issue("redaction", "redaction must be passed"))
    if "unsafe_tokens" in redaction:
        issues.append(_issue("redaction", "redaction summary must not include raw unsafe tokens"))

    true_ai = manifest.get("true_ai_opt_in") if isinstance(manifest.get("true_ai_opt_in"), dict) else {}
    if true_ai.get("status", "unknown") not in VALID_TRUE_AI_STATUSES:
        issues.append(_issue("true_ai_opt_in", "invalid true-AI status"))
    if true_ai.get("required") is True and true_ai.get("status") == "skipped_opt_in":
        issues.append(_issue("true_ai_opt_in", "true-AI skipped opt-in must not be required"))

    output_location = manifest.get("output_location") if isinstance(manifest.get("output_location"), dict) else {}
    if output_location.get("status") != "repo_external":
        issues.append(_issue("output_location", "output location must be repo_external"))
    if find_unsafe_tokens(json.dumps(manifest, ensure_ascii=False)):
        issues.append(_issue("redaction", "manifest contains unsafe token"))

    handoff_path = manifest_path.with_name("rc_handoff.md")
    try:
        handoff_text = handoff_path.read_text(encoding="utf-8")
    except OSError:
        issues.append(_issue("rc_handoff.md", "handoff markdown missing"))
        handoff_text = ""
    if handoff_text and find_unsafe_tokens(handoff_text):
        issues.append(_issue("rc_handoff.md", "handoff markdown contains unsafe token"))

    bundle_root = manifest_path.parent
    _check_json_artifact(bundle_root / "release_gate_report.json", "release_gate_report.json", issues)
    _check_json_artifact(bundle_root / "release_evidence" / "evidence.json", "release_evidence/evidence.json", issues)
    _check_text_artifact(bundle_root / "release_evidence" / "evidence.md", "release_evidence/evidence.md", issues)

    return {
        "schema_version": "1.0",
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }


def _check_json_artifact(path: Path, label: str, issues: list[dict[str, str]]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        issues.append(_issue(label, "generated artifact missing"))
        return
    if find_unsafe_tokens(text):
        issues.append(_issue(label, "generated artifact contains unsafe token"))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        issues.append(_issue(label, "generated artifact JSON unreadable"))
        return
    forbidden = _find_forbidden_keys(payload, FORBIDDEN_RELEASE_GATE_KEYS)
    if label == "release_gate_report.json" and forbidden:
        issues.append(_issue(label, "release gate report must not contain output_tail or diagnostic_tail"))


def _check_text_artifact(path: Path, label: str, issues: list[dict[str, str]]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        issues.append(_issue(label, "generated artifact missing"))
        return
    if find_unsafe_tokens(text):
        issues.append(_issue(label, "generated artifact contains unsafe token"))


def _find_forbidden_keys(value: Any, forbidden: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in forbidden:
                found.append(str(key))
            found.extend(_find_forbidden_keys(item, forbidden))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_forbidden_keys(item, forbidden))
    return found


def _inside_repo(path: Path) -> bool:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    try:
        resolved.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def _issue(field: str, message: str) -> dict[str, str]:
    safe_field = "[redacted]" if find_unsafe_tokens(field) else field
    safe_message = "[redacted]" if find_unsafe_tokens(message) else message
    return {"field": safe_field, "message": safe_message}


if __name__ == "__main__":
    raise SystemExit(main())
