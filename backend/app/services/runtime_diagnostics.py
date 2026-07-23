from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.runtime import RuntimePreflightError, RuntimePreflightResponse

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_CHECK_SCRIPT = _REPO_ROOT / "scripts" / "check_ai_runtime.py"
_ADTOF_ENV_KEYS = (
    "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE",
    "GROOVESCRIBE_ADTOF_CHECKPOINT",
    "GROOVESCRIBE_ADTOF_DEVICE",
    "GROOVESCRIBE_ADTOF_THRESHOLD",
    "GROOVESCRIBE_ADTOF_VERIFY_INPUT",
    "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR",
)


class RuntimeDiagnosticsService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        process_runner: ProcessRunner | None = None,
        runtime_check_script_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.process_runner = process_runner or subprocess.run
        self.runtime_check_script_path = runtime_check_script_path or _RUNTIME_CHECK_SCRIPT

    def get_preflight(self) -> RuntimePreflightResponse:
        checked_at = datetime.now(UTC)
        ai_python_path = Path(self.settings.ai_python_path).expanduser()
        ai_python_available = self._ai_python_available(ai_python_path)
        if not ai_python_available:
            return self._error_response(
                checked_at=checked_at,
                code="AI_PYTHON_NOT_FOUND",
                message="AI runtime Python executable is not available.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=False)},
            )

        command = [str(ai_python_path), str(self.runtime_check_script_path)]
        try:
            completed = self.process_runner(
                command,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=self.settings.runtime_preflight_timeout_seconds,
                env=self._runtime_env(),
            )
        except subprocess.TimeoutExpired:
            return self._error_response(
                checked_at=checked_at,
                code="RUNTIME_PREFLIGHT_TIMEOUT",
                message="Runtime preflight check timed out.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=True)},
            )
        except FileNotFoundError:
            return self._error_response(
                checked_at=checked_at,
                code="AI_PYTHON_NOT_FOUND",
                message="AI runtime Python executable is not available.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=False)},
            )

        if completed.returncode != 0:
            return self._error_response(
                checked_at=checked_at,
                code="RUNTIME_PREFLIGHT_FAILED",
                message="Runtime preflight command failed.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=True)},
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return self._error_response(
                checked_at=checked_at,
                code="RUNTIME_PREFLIGHT_INVALID_JSON",
                message="Runtime preflight returned an invalid response.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=True)},
            )

        if not isinstance(payload, dict):
            return self._error_response(
                checked_at=checked_at,
                code="RUNTIME_PREFLIGHT_INVALID_JSON",
                message="Runtime preflight returned an invalid response.",
                checks={"ai_python": self._ai_python_check(ai_python_path, available=True)},
            )
        return self._build_response(payload, checked_at=checked_at, ai_python_path=ai_python_path)

    def _runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GROOVESCRIBE_DEMUCS_DEVICE"] = self.settings.pipeline_demucs_device
        for key in _ADTOF_ENV_KEYS:
            env.pop(key, None)
        if self.settings.pipeline_pdf_renderer:
            env["GROOVESCRIBE_PDF_RENDERER"] = self.settings.pipeline_pdf_renderer
        return env

    def _build_response(
        self,
        payload: dict[str, Any],
        *,
        checked_at: datetime,
        ai_python_path: Path,
    ) -> RuntimePreflightResponse:
        runtime_checks = self._dict(payload.get("runtime_checks"))
        local_pipeline = self._dict(runtime_checks.get("local_pipeline"))
        demo_mock_ready = bool(local_pipeline.get("demo_mock_ready"))
        generic_baseline_ready = bool(local_pipeline.get("generic_baseline_ready"))
        missing_requirements = [self._redact_text(item) for item in self._string_list(local_pipeline.get("missing_requirements"))]
        if generic_baseline_ready:
            status = "ready"
        elif demo_mock_ready:
            status = "degraded"
        else:
            status = "not_ready"

        checks = {
            "ai_python": self._ai_python_check(ai_python_path, available=True),
            "ffmpeg": self._ffmpeg_check(payload, runtime_checks),
            "demucs": self._demucs_check(runtime_checks),
            "spectral_onset": self._spectral_onset_check(runtime_checks),
            "musescore_pdf": self._musescore_check(runtime_checks),
        }
        smoke_commands = self._sanitize_smoke_commands(self._dict(payload.get("smoke_commands")))
        return RuntimePreflightResponse(
            status=status,
            generic_baseline_ready=generic_baseline_ready,
            demo_mock_ready=demo_mock_ready,
            mock_ai_ready=demo_mock_ready,
            true_ai_ready=False,
            missing_requirements=missing_requirements,
            checks=checks,
            offline_evaluation={
                "adtof": {
                    "enabled": False,
                    "reason": "offline_evaluation_only",
                }
            },
            smoke_commands=smoke_commands,
            checked_at=checked_at,
        )

    def _error_response(
        self,
        *,
        checked_at: datetime,
        code: str,
        message: str,
        checks: dict[str, Any] | None = None,
    ) -> RuntimePreflightResponse:
        return RuntimePreflightResponse(
            status="error",
            generic_baseline_ready=False,
            demo_mock_ready=False,
            mock_ai_ready=False,
            true_ai_ready=False,
            missing_requirements=[],
            checks=checks or {},
            smoke_commands={},
            checked_at=checked_at,
            error=RuntimePreflightError(code=code, message=message),
        )

    def _ai_python_available(self, path: Path) -> bool:
        if path.is_absolute():
            return path.exists() and path.is_file()
        return True

    def _ai_python_check(self, path: Path, *, available: bool) -> dict[str, Any]:
        return {
            "available": available,
            "executable": path.name,
        }

    def _ffmpeg_check(self, payload: dict[str, Any], runtime_checks: dict[str, Any]) -> dict[str, Any]:
        ffmpeg_runtime = self._dict(runtime_checks.get("ffmpeg"))
        ffmpeg_command = self._dict(self._dict(payload.get("commands")).get("ffmpeg"))
        return {
            "ready": bool(ffmpeg_runtime.get("ready")),
            "available": bool(ffmpeg_command.get("available")),
            "command": "ffmpeg",
            "version": self._string_or_none(ffmpeg_command.get("version")),
        }

    def _demucs_check(self, runtime_checks: dict[str, Any]) -> dict[str, Any]:
        demucs = self._dict(runtime_checks.get("demucs"))
        package = self._dict(demucs.get("package"))
        command_probe = self._dict(demucs.get("command_probe"))
        return {
            "ready": bool(demucs.get("ready")),
            "package_available": bool(package.get("available")),
            "package_version": self._string_or_none(package.get("version")),
            "command_probe_exit_code": command_probe.get("exit_code"),
        }

    def _spectral_onset_check(self, runtime_checks: dict[str, Any]) -> dict[str, Any]:
        spectral_onset = self._dict(runtime_checks.get("spectral_onset"))
        return {
            "ready": bool(spectral_onset.get("ready")),
            "reason_code": self._string_or_none(spectral_onset.get("reason_code")),
        }


    def _musescore_check(self, runtime_checks: dict[str, Any]) -> dict[str, Any]:
        musescore = self._dict(runtime_checks.get("musescore_pdf"))
        return {
            "ready": bool(musescore.get("ready")),
            "optional_for_v1": True,
            "available_candidates": self._string_list(musescore.get("available_candidates")),
            "configured_renderer": self._redact_text(str(musescore.get("configured_renderer")))
            if musescore.get("configured_renderer")
            else None,
        }

    def _sanitize_smoke_commands(self, smoke_commands: dict[str, Any]) -> dict[str, str]:
        return {
            str(name): self._redact_text(str(command))
            for name, command in smoke_commands.items()
            if isinstance(command, str)
        }

    def _redact_text(self, value: str) -> str:
        replacements = {
            str(_REPO_ROOT): "<repo>",
            str(Path.home()): "<home>",
            self.settings.ai_python_path: "<ai_python>",
        }
        redacted = value
        for source, target in replacements.items():
            if source:
                redacted = redacted.replace(source, target)
        redacted = re.sub(r"/Users/[^\s\"']+", "<local-path>", redacted)
        redacted = re.sub(r"/private/tmp/[^\s\"']+", "<local-path>", redacted)
        redacted = re.sub(r"/tmp/[^\s\"']+", "<local-path>", redacted)
        redacted = re.sub(r"/private/var/[^\s\"']+", "<local-path>", redacted)
        redacted = re.sub(r"/var/folders/[^\s\"']+", "<local-path>", redacted)
        return redacted

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _string_or_none(self, value: Any) -> str | None:
        return str(value) if value is not None else None
