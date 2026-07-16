from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.redaction import find_unsafe_tokens
    from scripts.true_ai_runtime_defaults import (
        DEFAULT_ADTOF_DEVICE,
        DEFAULT_ADTOF_THRESHOLD,
        DEFAULT_ADTOF_VERIFY_INPUT,
        DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
        DEFAULT_DEMUCS_DEVICE,
        public_env_summary,
        true_ai_runtime_env,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens
    from true_ai_runtime_defaults import (
        DEFAULT_ADTOF_DEVICE,
        DEFAULT_ADTOF_THRESHOLD,
        DEFAULT_ADTOF_VERIFY_INPUT,
        DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
        DEFAULT_DEMUCS_DEVICE,
        public_env_summary,
        true_ai_runtime_env,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check GrooveScribe V1 true-AI local runtime setup.")
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", ".venv-ai/bin/python"))
    parser.add_argument("--adtof-command-template")
    parser.add_argument("--adtof-verify-input", type=Path, default=DEFAULT_ADTOF_VERIFY_INPUT)
    parser.add_argument("--adtof-verify-output-dir", type=Path, default=DEFAULT_ADTOF_VERIFY_OUTPUT_DIR)
    parser.add_argument("--demucs-device", default=DEFAULT_DEMUCS_DEVICE)
    parser.add_argument("--adtof-device", default=DEFAULT_ADTOF_DEVICE)
    parser.add_argument("--adtof-threshold", default=DEFAULT_ADTOF_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = check_true_ai_setup(
        ai_python=args.ai_python,
        adtof_command_template=args.adtof_command_template,
        verify_input=args.adtof_verify_input,
        verify_output_dir=args.adtof_verify_output_dir,
        demucs_device=args.demucs_device,
        adtof_device=args.adtof_device,
        adtof_threshold=args.adtof_threshold,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready" else 1


def check_true_ai_setup(
    *,
    ai_python: str = ".venv-ai/bin/python",
    adtof_command_template: str | None = None,
    verify_input: Path = DEFAULT_ADTOF_VERIFY_INPUT,
    verify_output_dir: Path = DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
    demucs_device: str = DEFAULT_DEMUCS_DEVICE,
    adtof_device: str = DEFAULT_ADTOF_DEVICE,
    adtof_threshold: str = DEFAULT_ADTOF_THRESHOLD,
    runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    checked = checked_at or datetime.now(UTC)
    env = {
        **os.environ,
        **true_ai_runtime_env(
            adtof_command_template=adtof_command_template,
            verify_input=verify_input,
            verify_output_dir=verify_output_dir,
            demucs_device=demucs_device,
            adtof_device=adtof_device,
            adtof_threshold=adtof_threshold,
        ),
    }
    try:
        completed = runner(
            [ai_python, "scripts/check_ai_runtime.py"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _finalize(
            {
                "schema_version": "1.0",
                "status": "blocked",
                "checked_at": checked.isoformat(),
                "true_ai_ready": False,
                "env": public_env_summary(env),
                "checks": {"runtime": {"status": "failed", "reason": "runtime_check_failed"}},
                "missing_requirements": ["AI runtime check could not be executed."],
                "next_steps": ["Confirm .venv-ai exists and run npm run check:true-ai again."],
            }
        )

    payload = _parse_json(completed.stdout)
    runtime_checks = _dict(payload.get("runtime_checks"))
    local_pipeline = _dict(runtime_checks.get("local_pipeline"))
    adtof = _dict(runtime_checks.get("adtof_pytorch"))
    demucs = _dict(runtime_checks.get("demucs"))
    ffmpeg = _dict(runtime_checks.get("ffmpeg"))
    true_ai_ready = bool(local_pipeline.get("true_ai_ready"))
    missing = _safe_list(local_pipeline.get("missing_requirements", []))
    status = "ready" if completed.returncode == 0 and true_ai_ready else "blocked"
    return _finalize(
        {
            "schema_version": "1.0",
            "status": status,
            "checked_at": checked.isoformat(),
            "true_ai_ready": true_ai_ready,
            "env": public_env_summary(env),
            "checks": {
                "ffmpeg": {"ready": bool(ffmpeg.get("ready"))},
                "demucs": {"ready": bool(demucs.get("ready"))},
                "adtof": _adtof_summary(adtof),
            },
            "missing_requirements": missing,
            "next_steps": _next_steps(true_ai_ready, adtof, missing),
        }
    )


def _adtof_summary(adtof: dict[str, Any]) -> dict[str, Any]:
    verification = _dict(adtof.get("output_verification"))
    return {
        "ready": bool(adtof.get("ready")),
        "status_code": adtof.get("status_code") or verification.get("status_code") or "unknown",
        "template_configured": bool(adtof.get("template_configured")),
        "template_executable": bool(adtof.get("template_executable")),
        "output_verified": bool(adtof.get("output_verified")),
        "event_count": verification.get("event_count"),
    }


def _next_steps(true_ai_ready: bool, adtof: dict[str, Any], missing: list[str]) -> list[str]:
    if true_ai_ready:
        return ["Start with npm run dev:true-ai -- --backend-port 8001 --frontend-port 5174, then choose True-AI V1 preset."]
    status_code = str(adtof.get("status_code") or "unknown")
    steps = {
        "not_configured": "Set the ADTOF template env or use npm run dev:true-ai.",
        "verify_input_missing": "Create a verification stem and set GROOVESCRIBE_ADTOF_VERIFY_INPUT.",
        "verify_input_not_found": "Regenerate the drums stem verification input or pass --adtof-verify-input.",
        "executable_missing": "Confirm .venv-ai/bin/adtof exists and adtof-pytorch is installed.",
        "template_invalid": "ADTOF command template must include {input} and {output}.",
    }
    return [steps.get(status_code, "Fix true-AI runtime requirements, then rerun npm run check:true-ai.")] + missing[:2]


def _parse_json(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    safe: list[str] = []
    for item in value:
        text = str(item)
        safe.append("true_ai_runtime_missing_requirement" if find_unsafe_tokens(text) else text)
    return safe


def _finalize(report: dict[str, Any]) -> dict[str, Any]:
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        report["status"] = "failed"
        report["true_ai_ready"] = False
        report["checks"] = {"runtime": {"status": "failed", "reason": "redaction_failed"}}
        report["missing_requirements"] = ["True-AI setup report redaction failed."]
        report["next_steps"] = ["Rerun setup doctor with public-safe configuration labels."]
        report["redaction"] = {"status": "failed", "unsafe_token_count": len(unsafe)}
    return report


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
