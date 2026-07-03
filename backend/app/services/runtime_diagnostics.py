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
        env["GROOVESCRIBE_ADTOF_DEVICE"] = self.settings.pipeline_adtof_device
        env["GROOVESCRIBE_ADTOF_THRESHOLD"] = str(self.settings.pipeline_adtof_threshold)
        if self.settings.pipeline_adtof_command_template:
            env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"] = self.settings.pipeline_adtof_command_template
        if self.settings.pipeline_adtof_checkpoint_path:
            env["GROOVESCRIBE_ADTOF_CHECKPOINT"] = self.settings.pipeline_adtof_checkpoint_path
        if self.settings.pipeline_adtof_verify_input_path:
            env["GROOVESCRIBE_ADTOF_VERIFY_INPUT"] = self.settings.pipeline_adtof_verify_input_path
        if self.settings.pipeline_adtof_verify_output_dir:
            env["GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"] = self.settings.pipeline_adtof_verify_output_dir
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
        mock_ai_ready = bool(local_pipeline.get("mock_ai_ready"))
        true_ai_ready = bool(local_pipeline.get("true_ai_ready"))
        missing_requirements = [self._redact_text(item) for item in self._string_list(local_pipeline.get("missing_requirements"))]
        if true_ai_ready:
            status = "ready"
        elif mock_ai_ready:
            status = "degraded"
        else:
            status = "not_ready"

        checks = {
            "ai_python": self._ai_python_check(ai_python_path, available=True),
            "ffmpeg": self._ffmpeg_check(payload, runtime_checks),
            "demucs": self._demucs_check(runtime_checks),
            "adtof": self._adtof_check(runtime_checks),
            "musescore_pdf": self._musescore_check(runtime_checks),
        }
        smoke_commands = self._sanitize_smoke_commands(self._dict(payload.get("smoke_commands")))
        return RuntimePreflightResponse(
            status=status,
            mock_ai_ready=mock_ai_ready,
            true_ai_ready=true_ai_ready,
            missing_requirements=missing_requirements,
            checks=checks,
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

    def _adtof_check(self, runtime_checks: dict[str, Any]) -> dict[str, Any]:
        adtof = self._dict(runtime_checks.get("adtof_pytorch"))
        output_verification = self._dict(adtof.get("output_verification"))
        status_code = self._string_or_none(adtof.get("status_code")) or "not_configured"
        output_reason = self._string_or_none(output_verification.get("reason"))
        return {
            "ready": bool(adtof.get("ready")),
            "status_code": status_code,
            "summary": self._adtof_summary(status_code),
            "next_steps": self._adtof_next_steps(status_code),
            "configured": bool(adtof.get("configured")),
            "template_configured": bool(adtof.get("template_configured")),
            "template_executable": bool(adtof.get("template_executable")),
            "runtime_verified": bool(adtof.get("runtime_verified")),
            "output_verified": bool(adtof.get("output_verified")),
            "output_verification_attempted": bool(output_verification.get("attempted")),
            "output_verification_reason": self._redact_text(output_reason) if output_reason else None,
            "event_count": output_verification.get("event_count"),
            "device": self._string_or_none(adtof.get("device")),
            "threshold": self._string_or_none(adtof.get("threshold")),
            "missing_placeholders": self._string_list(adtof.get("missing_placeholders")),
            "required_env": self._string_list(adtof.get("required_env")),
            "optional_env": self._string_list(adtof.get("optional_env")),
        }

    def _adtof_summary(self, status_code: str) -> str:
        return {
            "ready": "ADTOF 已成功產生可解析且含 note-on events 的 raw_drum.mid。",
            "not_configured": "尚未設定 ADTOF command template。",
            "template_invalid": "ADTOF command template 格式不完整或無法解析。",
            "executable_missing": "ADTOF command executable 或 Python module 不可用。",
            "verify_input_missing": "尚未提供 ADTOF verification input drums stem。",
            "verify_input_not_found": "ADTOF verification input 路徑不存在。",
            "command_failed": "ADTOF verification command 執行失敗。",
            "output_missing": "ADTOF command 未產生 raw_drum.mid。",
            "output_unparseable": "ADTOF 產生的 raw_drum.mid 無法解析。",
            "output_no_events": "ADTOF 產生的 raw_drum.mid 沒有 note-on events。",
        }.get(status_code, "ADTOF runtime 尚未 ready。")

    def _adtof_next_steps(self, status_code: str) -> list[str]:
        return {
            "ready": ["可以執行 opt-in true-AI smoke；V1 預設仍維持 mock-ai flow。"],
            "not_configured": [
                "設定 GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE，template 必須包含 {input} 與 {output}。",
                "可選擇加入 {device}、{threshold}、{checkpoint} placeholder。",
            ],
            "template_invalid": [
                "修正 GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE，確認 shell quoting 可被 shlex 解析。",
                "確認 template 包含 {input} 與 {output}。",
            ],
            "executable_missing": [
                "確認 ADTOF CLI 或 adtof Python module 已安裝在 AI runtime。",
                "若使用 CLI，請確認 command template 的第一個可執行檔在 PATH 或為絕對路徑。",
            ],
            "verify_input_missing": [
                "先執行 normalize 與 Demucs separation，產生 drums.wav。",
                "設定 GROOVESCRIBE_ADTOF_VERIFY_INPUT 指向該 drums.wav。",
            ],
            "verify_input_not_found": [
                "確認 GROOVESCRIBE_ADTOF_VERIFY_INPUT 指向已存在的 drums.wav。",
            ],
            "command_failed": [
                "直接執行 redacted smoke command 對照本機 stderr。",
                "檢查 checkpoint、device、threshold 與 ADTOF CLI 參數是否符合安裝版本。",
            ],
            "output_missing": [
                "確認 ADTOF template 的 {output} 對應到 raw MIDI 輸出參數。",
                "檢查 ADTOF CLI 是否需要不同的輸出 flag，例如 --out 或 --output。",
            ],
            "output_unparseable": [
                "確認 ADTOF 輸出為 MIDI 檔，不是 log、JSON 或空檔。",
            ],
            "output_no_events": [
                "換用更清楚的 drums stem 或調整 threshold。",
                "確認 checkpoint/model 是否適用於目前輸入音訊。",
            ],
        }.get(status_code, ["查看 runtime preflight missing requirements 並依文件逐項修復。"])

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
