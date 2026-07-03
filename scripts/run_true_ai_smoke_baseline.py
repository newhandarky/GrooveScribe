from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from scripts.inspect_midi import inspect_midi

_REPO_ROOT = Path(__file__).resolve().parents[1]
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class BaselineConfig:
    input_path: Path
    output_root: Path
    run_id: str
    ai_python: str
    demucs_device: str
    adtof_command_template: str | None
    adtof_checkpoint: str | None
    adtof_device: str
    adtof_threshold: str
    timeout_seconds: int
    export_pdf: bool = True
    fail_on_blocked: bool = False


@dataclass(frozen=True)
class BaselineRunResult:
    status: str
    report_path: Path
    return_code: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an opt-in true-AI smoke and write an artifact baseline report.")
    parser.add_argument(
        "--input",
        type=Path,
        default=_REPO_ROOT / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_clean_drum_pattern.wav",
    )
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/groovescribe-true-ai-baseline"))
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", sys.executable))
    parser.add_argument("--demucs-device", default=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"))
    parser.add_argument("--adtof-command-template", default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"))
    parser.add_argument("--adtof-checkpoint", default=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"))
    parser.add_argument("--adtof-device", default=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"))
    parser.add_argument("--adtof-threshold", default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", "0.5"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--no-export-pdf", action="store_true")
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_baseline(
        BaselineConfig(
            input_path=args.input,
            output_root=args.output_root,
            run_id=args.run_id,
            ai_python=args.ai_python,
            demucs_device=args.demucs_device,
            adtof_command_template=args.adtof_command_template,
            adtof_checkpoint=args.adtof_checkpoint,
            adtof_device=args.adtof_device,
            adtof_threshold=args.adtof_threshold,
            timeout_seconds=args.timeout_seconds,
            export_pdf=not args.no_export_pdf,
            fail_on_blocked=args.fail_on_blocked,
        )
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "baseline_report": str(result.report_path),
            },
            indent=2,
        )
    )
    return result.return_code


def run_baseline(
    config: BaselineConfig,
    *,
    process_runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> BaselineRunResult:
    checked = checked_at or datetime.now(UTC)
    output_dir = (config.output_root / config.run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "baseline.json"

    preflight_result = _run_json_command(
        [config.ai_python, "scripts/check_ai_runtime.py"],
        process_runner=process_runner,
        env=_runtime_env(config),
        timeout=120,
    )
    if preflight_result["returncode"] != 0 or not isinstance(preflight_result.get("json"), dict):
        report = _blocked_report(
            config,
            checked_at=checked,
            reason="runtime preflight command failed or returned invalid JSON",
            output_dir=output_dir,
            preflight=preflight_result.get("json"),
        )
        _write_report(report_path, report)
        return BaselineRunResult("blocked", report_path, 2 if config.fail_on_blocked else 0)

    preflight = preflight_result["json"]
    local_pipeline = _dict(_dict(preflight.get("runtime_checks")).get("local_pipeline"))
    if not local_pipeline.get("true_ai_ready"):
        report = _blocked_report(
            config,
            checked_at=checked,
            reason=_blocked_reason(preflight),
            output_dir=output_dir,
            preflight=preflight,
        )
        _write_report(report_path, report)
        return BaselineRunResult("blocked", report_path, 2 if config.fail_on_blocked else 0)

    pipeline_command = _pipeline_command(config, output_dir)
    pipeline_result = _run_json_command(
        pipeline_command,
        process_runner=process_runner,
        env=_runtime_env(config),
        timeout=config.timeout_seconds,
    )
    report = _completed_or_failed_report(
        config,
        checked_at=checked,
        output_dir=output_dir,
        preflight=preflight,
        pipeline_result=pipeline_result,
    )
    _write_report(report_path, report)
    return BaselineRunResult(str(report["status"]), report_path, 0 if report["status"] == "completed" else 1)


def _runtime_env(config: BaselineConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["AI_PYTHON"] = config.ai_python
    env["GROOVESCRIBE_DEMUCS_DEVICE"] = config.demucs_device
    env["GROOVESCRIBE_ADTOF_DEVICE"] = config.adtof_device
    env["GROOVESCRIBE_ADTOF_THRESHOLD"] = config.adtof_threshold
    if config.adtof_command_template:
        env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"] = config.adtof_command_template
    if config.adtof_checkpoint:
        env["GROOVESCRIBE_ADTOF_CHECKPOINT"] = config.adtof_checkpoint
    return env


def _pipeline_command(config: BaselineConfig, output_dir: Path) -> list[str]:
    command = [
        config.ai_python,
        "scripts/run_local_pipeline.py",
        "--input",
        str(config.input_path),
        "--output-dir",
        str(output_dir),
        "--demucs-device",
        config.demucs_device,
        "--adtof-device",
        config.adtof_device,
        "--adtof-threshold",
        config.adtof_threshold,
    ]
    if config.adtof_command_template:
        command.extend(["--adtof-command-template", config.adtof_command_template])
    if config.adtof_checkpoint:
        command.extend(["--adtof-checkpoint", config.adtof_checkpoint])
    if config.export_pdf:
        command.append("--export-pdf")
    return command


def _run_json_command(
    command: list[str],
    *,
    process_runner: ProcessRunner,
    env: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    try:
        completed = process_runner(
            command,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": None, "json": None, "error": "timeout", "command": _safe_command(command)}
    except FileNotFoundError:
        return {"returncode": None, "json": None, "error": "executable_not_found", "command": _safe_command(command)}

    payload = None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    return {
        "returncode": completed.returncode,
        "json": payload,
        "command": _safe_command(command),
    }


def _blocked_report(
    config: BaselineConfig,
    *,
    checked_at: datetime,
    reason: str,
    output_dir: Path,
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "checked_at": checked_at.isoformat(),
        "input_fixture": _display_path(config.input_path),
        "output_dir_name": output_dir.name,
        "blocked_reason": reason,
        "runtime": _runtime_summary(config, preflight),
        "preflight": _preflight_summary(preflight),
        "artifacts": {},
        "inspection": {},
    }


def _completed_or_failed_report(
    config: BaselineConfig,
    *,
    checked_at: datetime,
    output_dir: Path,
    preflight: dict[str, Any],
    pipeline_result: dict[str, Any],
) -> dict[str, Any]:
    pipeline_payload = _dict(pipeline_result.get("json"))
    artifact_paths = _artifact_paths(output_dir)
    pipeline_log = _read_json(artifact_paths["pipeline_log"]["path"])
    drum_events = _read_json(artifact_paths["drum_events"]["path"])
    raw_inspection = _inspect_optional_midi(artifact_paths["raw_midi"]["path"])
    processed_inspection = _inspect_optional_midi(artifact_paths["processed_midi"]["path"])
    required_available = all(
        artifact_paths[name]["available"]
        for name in ("raw_midi", "processed_midi", "musicxml", "pipeline_log")
    )
    status = "completed" if pipeline_result["returncode"] == 0 and required_available else "failed"
    return {
        "schema_version": "1.0",
        "status": status,
        "checked_at": checked_at.isoformat(),
        "input_fixture": _display_path(config.input_path),
        "output_dir_name": output_dir.name,
        "runtime": _runtime_summary(config, preflight),
        "preflight": _preflight_summary(preflight),
        "pipeline": {
            "returncode": pipeline_result["returncode"],
            "status": pipeline_payload.get("status"),
            "failed_stage": pipeline_payload.get("failed_stage"),
            "stage_count": len(_list(pipeline_log.get("stages") or pipeline_log.get("stage_reports"))),
            "warnings": _collect_pipeline_warnings(pipeline_log, drum_events),
        },
        "artifacts": {name: _artifact_report(item, output_dir) for name, item in artifact_paths.items()},
        "inspection": {
            "raw_midi": raw_inspection,
            "processed_midi": processed_inspection,
            "drum_events": _drum_events_summary(drum_events),
        },
        "exports": {
            "midi": _export_status(artifact_paths["processed_midi"]),
            "musicxml": _export_status(artifact_paths["musicxml"]),
            "pdf": _export_status(artifact_paths["pdf"], optional=True),
        },
    }


def _artifact_paths(output_dir: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "normalized_audio": output_dir / "audio" / "normalized.wav",
        "drums_stem": output_dir / "stems" / "drums.wav",
        "raw_midi": output_dir / "midi" / "raw_drum.mid",
        "processed_midi": output_dir / "midi" / "processed_drum.mid",
        "drum_events": output_dir / "midi" / "drum_events.json",
        "musicxml": output_dir / "notation" / "score.musicxml",
        "pdf": output_dir / "exports" / "score.pdf",
        "pipeline_log": output_dir / "logs" / "pipeline.json",
    }
    return {
        name: {
            "path": path,
            "available": path.exists() and path.is_file() and path.stat().st_size > 0,
            "file_size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
        }
        for name, path in paths.items()
    }


def _artifact_report(item: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "path": _relative_artifact_path(item["path"], output_dir),
        "available": item["available"],
        "file_size_bytes": item["file_size_bytes"],
    }


def _export_status(item: dict[str, Any], *, optional: bool = False) -> dict[str, Any]:
    status = "available" if item["available"] else "unavailable"
    return {
        "status": status,
        "optional": optional,
        "file_size_bytes": item["file_size_bytes"],
    }


def _inspect_optional_midi(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return {"available": False}
    try:
        return {"available": True, **inspect_midi(path)}
    except Exception as exc:
        return {"available": True, "parse_error": str(exc)}


def _drum_events_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": bool(payload),
        "event_count": payload.get("event_count"),
        "processed_drum_counts": _dict(payload.get("processed_drum_counts")),
        "raw_note_histogram": _dict(payload.get("raw_note_histogram")),
        "warnings": _list(payload.get("warnings")),
    }


def _preflight_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    runtime_checks = _dict(payload.get("runtime_checks"))
    local_pipeline = _dict(runtime_checks.get("local_pipeline"))
    adtof = _dict(runtime_checks.get("adtof_pytorch"))
    output_verification = _dict(adtof.get("output_verification"))
    return {
        "available": True,
        "mock_ai_ready": bool(local_pipeline.get("mock_ai_ready")),
        "true_ai_ready": bool(local_pipeline.get("true_ai_ready")),
        "missing_requirements": _list(local_pipeline.get("missing_requirements")),
        "adtof_status_code": adtof.get("status_code"),
        "adtof_event_count": output_verification.get("event_count"),
    }


def _runtime_summary(config: BaselineConfig, preflight: dict[str, Any] | None) -> dict[str, Any]:
    python = _dict(preflight.get("python")) if preflight else {}
    return {
        "ai_python": Path(config.ai_python).name,
        "python_version": python.get("version"),
        "demucs_device": config.demucs_device,
        "adtof_template_configured": bool(config.adtof_command_template),
        "adtof_checkpoint_configured": bool(config.adtof_checkpoint),
        "adtof_device": config.adtof_device,
        "adtof_threshold": config.adtof_threshold,
    }


def _blocked_reason(preflight: dict[str, Any]) -> str:
    summary = _preflight_summary(preflight)
    missing = summary.get("missing_requirements") or []
    status_code = summary.get("adtof_status_code")
    if missing:
        return "; ".join(str(item) for item in missing)
    if status_code and status_code != "ready":
        return f"ADTOF status_code={status_code}"
    return "true-AI runtime is not ready"


def _collect_pipeline_warnings(pipeline_log: dict[str, Any], drum_events: dict[str, Any]) -> list[str]:
    warnings: set[str] = set(str(item) for item in _list(drum_events.get("warnings")))
    for stage in _list(pipeline_log.get("stages") or pipeline_log.get("stage_reports")):
        if not isinstance(stage, dict):
            continue
        report = _dict(stage.get("report"))
        warnings.update(str(item) for item in _list(report.get("warnings")))
        pdf_report = _dict(report.get("pdf"))
        warnings.update(str(item) for item in _list(pdf_report.get("warnings")))
    return sorted(warnings)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _display_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return f"<external>/{resolved.name}"


def _relative_artifact_path(path: Path, output_dir: Path) -> str:
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return path.name


def _safe_command(command: list[str]) -> list[str]:
    if not command:
        return []
    safe = [Path(command[0]).name]
    safe.extend(Path(item).name if item.endswith(".py") else item for item in command[1:])
    return safe


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
