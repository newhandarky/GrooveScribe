from __future__ import annotations

from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from app.services.internal_job_detail_service import InternalJobPipelineReadModel

REDACTED = "[redacted]"
_SENSITIVE_KEY_PARTS = (
    "command",
    "template",
    "checkpoint",
    "stderr",
    "stdout",
    "stack",
    "traceback",
    "token",
    "secret",
    "env",
)
_LOCAL_PATH_PREFIXES = ("/Users/", "/tmp/", "/private/tmp/", "/var/folders/", "/private/var/")


def redact_pipeline_snapshot(snapshot: InternalJobPipelineReadModel) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload["artifacts"] = _redact_artifacts(payload.get("artifacts", {}))
    payload["stage_reports"] = [_redact_stage_report(report) for report in payload.get("stage_reports", [])]
    payload["error"] = _redact_sensitive(payload.get("error"))
    payload["warnings"] = _redact_sensitive(payload.get("warnings", []))
    return payload


def _redact_stage_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": report.get("name"),
        "status": report.get("status"),
        "runtime_seconds": report.get("runtime_seconds"),
        "artifacts": _redact_artifacts(report.get("artifacts", {})),
        "report": _redact_sensitive(report.get("report", {})),
        "warnings": _redact_sensitive(report.get("warnings", [])),
        "error": _redact_sensitive(report.get("error")),
    }


def _redact_artifacts(artifacts: Any) -> dict[str, str]:
    if not isinstance(artifacts, dict):
        return {}
    return {str(key): value if _is_storage_key(value) else REDACTED for key, value in artifacts.items()}


def _redact_sensitive(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): _redact_sensitive(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(item, key=key) for item in value]
    if isinstance(value, str):
        return REDACTED if _is_sensitive_string(value) else value
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _is_sensitive_string(value: str) -> bool:
    if any(value.startswith(prefix) for prefix in _LOCAL_PATH_PREFIXES):
        return True
    lowered = value.lower()
    return "traceback" in lowered or "stack trace" in lowered


def _is_storage_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if _is_sensitive_string(value):
        return False
    if value.startswith("/") or value.strip() != value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and not any(part in {"", ".", ".."} for part in path.parts)
