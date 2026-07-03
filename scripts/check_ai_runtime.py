from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_pipeline.transcription.midi_validation import count_note_on_events

PYTHON_PACKAGES = [
    "torch",
    "torchaudio",
    "demucs",
    "mido",
    "pretty_midi",
    "music21",
    "fastapi",
    "celery",
]
COMMANDS = ["ffmpeg", "musescore", "mscore", "MuseScore"]
DEMUCS_DEVICE_ENV = "GROOVESCRIBE_DEMUCS_DEVICE"
ADTOF_TEMPLATE_ENV = "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"
ADTOF_CHECKPOINT_ENV = "GROOVESCRIBE_ADTOF_CHECKPOINT"
ADTOF_DEVICE_ENV = "GROOVESCRIBE_ADTOF_DEVICE"
ADTOF_THRESHOLD_ENV = "GROOVESCRIBE_ADTOF_THRESHOLD"
ADTOF_VERIFY_INPUT_ENV = "GROOVESCRIBE_ADTOF_VERIFY_INPUT"
ADTOF_VERIFY_OUTPUT_DIR_ENV = "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"
PDF_RENDERER_ENV = "GROOVESCRIBE_PDF_RENDERER"
DEFAULT_ADTOF_TEMPLATE = (
    f"{sys.executable} -m adtof transcribe --input {{input}} --output {{output}} "
    "--device {device} --threshold {threshold}"
)


def main() -> int:
    demucs_device = os.environ.get(DEMUCS_DEVICE_ENV, "auto")
    adtof_template = os.environ.get(ADTOF_TEMPLATE_ENV)
    adtof_checkpoint = os.environ.get(ADTOF_CHECKPOINT_ENV)
    adtof_device = os.environ.get(ADTOF_DEVICE_ENV, "cpu")
    adtof_threshold = os.environ.get(ADTOF_THRESHOLD_ENV, "0.5")
    adtof_verify_input = os.environ.get(ADTOF_VERIFY_INPUT_ENV)
    adtof_verify_output_dir = os.environ.get(ADTOF_VERIFY_OUTPUT_DIR_ENV)
    pdf_renderer = os.environ.get(PDF_RENDERER_ENV)
    command_statuses = {name: _command_status(name) for name in COMMANDS}
    package_statuses = {name: _package_status(name) for name in PYTHON_PACKAGES}
    demucs_check = _demucs_runtime_check(package_statuses, device=demucs_device)
    adtof_check = _adtof_runtime_check(
        adtof_template,
        adtof_checkpoint,
        device=adtof_device,
        threshold=adtof_threshold,
        verify_input=adtof_verify_input,
        verify_output_dir=adtof_verify_output_dir,
    )
    musescore_check = _musescore_runtime_check(command_statuses, configured_renderer=pdf_renderer)
    ffmpeg_ready = command_statuses["ffmpeg"]["available"]
    true_pipeline_missing = _true_pipeline_missing(
        ffmpeg_ready=ffmpeg_ready,
        demucs_ready=demucs_check["ready"],
        adtof_ready=adtof_check["ready"],
    )
    payload = {
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
        "commands": command_statuses,
        "python_packages": package_statuses,
        "environment": {
            ADTOF_TEMPLATE_ENV: _redact_empty(adtof_template),
            ADTOF_CHECKPOINT_ENV: _redact_empty(adtof_checkpoint),
            DEMUCS_DEVICE_ENV: demucs_device,
            ADTOF_DEVICE_ENV: adtof_device,
            ADTOF_THRESHOLD_ENV: adtof_threshold,
            ADTOF_VERIFY_INPUT_ENV: _redact_empty(adtof_verify_input),
            ADTOF_VERIFY_OUTPUT_DIR_ENV: _redact_empty(adtof_verify_output_dir),
            PDF_RENDERER_ENV: _redact_empty(pdf_renderer),
        },
        "runtime_checks": {
            "ffmpeg": {"ready": ffmpeg_ready},
            "demucs": demucs_check,
            "adtof_pytorch": adtof_check,
            "musescore_pdf": musescore_check,
            "local_pipeline": {
                "mock_ai_ready": ffmpeg_ready,
                "true_ai_ready": not true_pipeline_missing,
                "missing_requirements": true_pipeline_missing,
            },
        },
        "smoke_commands": {
            "ffmpeg": "ffmpeg -version",
            "runtime_check": f"PYTHONPATH=. {sys.executable} scripts/check_ai_runtime.py",
            "demucs_probe": f"{sys.executable} -m demucs --help",
            "normalize_fixture": (
                f"PYTHONPATH=. {sys.executable} scripts/run_normalize_audio.py "
                "--input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav "
                "--output-dir /tmp/groovescribe-normalized"
            ),
            "local_pipeline_mock": (
                f"PYTHONPATH=. {sys.executable} scripts/run_local_pipeline.py "
                "--input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav "
                "--output-dir /tmp/groovescribe-fixture-run --mock-ai"
            ),
            "local_pipeline_true_ai": (
                "PYTHONPATH=. "
                f"{ADTOF_TEMPLATE_ENV}='...' "
                f"{ADTOF_VERIFY_INPUT_ENV}='/tmp/groovescribe-stems/drums.wav' "
                f"{sys.executable} scripts/run_local_pipeline.py "
                "--input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav "
                "--output-dir /tmp/groovescribe-true-ai-run "
                f"--adtof-command-template \"${ADTOF_TEMPLATE_ENV}\""
            ),
        },
    }
    print(json.dumps(payload, indent=2))
    return 0


def _command_status(name: str) -> dict:
    path = shutil.which(name)
    if path is None:
        return {"available": False, "path": None, "version": None}

    version = None
    try:
        completed = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.stdout:
            version = completed.stdout.splitlines()[0]
        elif completed.stderr:
            version = completed.stderr.splitlines()[0]
    except (OSError, subprocess.TimeoutExpired):
        version = None

    return {"available": True, "path": path, "version": version}


def _package_status(name: str) -> dict:
    available = importlib.util.find_spec(name) is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return {"available": available, "version": version}


def _demucs_runtime_check(package_statuses: dict[str, dict], *, device: str) -> dict:
    command_probe = _run_probe([sys.executable, "-m", "demucs", "--help"], timeout=20)
    return {
        "ready": package_statuses["demucs"]["available"] and command_probe["exit_code"] == 0,
        "package": package_statuses["demucs"],
        "command": [sys.executable, "-m", "demucs", "--help"],
        "device": device,
        "command_probe": command_probe,
    }


def _adtof_runtime_check(
    command_template: str | None,
    checkpoint: str | None,
    *,
    device: str = "cpu",
    threshold: str = "0.5",
    verify_input: str | None = None,
    verify_output_dir: str | None = None,
) -> dict:
    template = command_template or DEFAULT_ADTOF_TEMPLATE
    try:
        parts = shlex.split(template)
    except ValueError as exc:
        return {
            "ready": False,
            "status_code": "template_invalid",
            "template_configured": command_template is not None,
            "template_executable": False,
            "command_probe_passed": False,
            "runtime_verified": False,
            "output_verified": False,
            "configured": command_template is not None,
            "device": device,
            "threshold": threshold,
            "configuration_source": (
                ADTOF_TEMPLATE_ENV if command_template is not None else "default_adapter_template"
            ),
            "command_template": template,
            "required_env": [ADTOF_TEMPLATE_ENV],
            "optional_env": [
                ADTOF_CHECKPOINT_ENV,
                ADTOF_VERIFY_INPUT_ENV,
                ADTOF_VERIFY_OUTPUT_DIR_ENV,
            ],
            "checkpoint_path": checkpoint,
            "placeholders": [],
            "missing_placeholders": ["input", "output"],
            "example_command": [],
            "executable_check": {"available": False, "reason": f"template parse failed: {exc}"},
            "output_verification": {
                "verified": False,
                "attempted": False,
                "status_code": "template_invalid",
                "reason": f"template parse failed: {exc}",
            },
            "python_module": _module_status("adtof"),
            "note": (
                "ADTOF ready means a configured template actually produced a parseable "
                "raw_drum.mid with note-on events. Executable template checks alone are not enough."
            ),
        }
    placeholders = sorted(_find_placeholders(parts))
    missing_placeholders = [name for name in ("input", "output") if name not in placeholders]
    example_command = _format_adtof_template(
        parts,
        input_path=Path("/tmp/groovescribe-stems/drums.wav"),
        output_path=Path("/tmp/groovescribe-midi/raw_drum.mid"),
        checkpoint=checkpoint,
        device=device,
        threshold=threshold,
    )
    executable_check = _command_or_module_available(example_command)
    module_status = _module_status("adtof")
    template_configured = command_template is not None
    template_executable = not missing_placeholders and executable_check["available"]
    if not template_configured:
        output_verification = _verification_skipped(
            status_code="not_configured",
            reason=f"{ADTOF_TEMPLATE_ENV} is not set",
        )
    elif missing_placeholders:
        output_verification = _verification_skipped(
            status_code="template_invalid",
            reason="ADTOF command template must include {input} and {output}",
        )
    elif not executable_check["available"]:
        output_verification = _verification_skipped(
            status_code="executable_missing",
            reason="ADTOF command executable or Python module is not available",
        )
    else:
        output_verification = _verify_adtof_output(
            parts,
            checkpoint=checkpoint,
            verify_input=verify_input,
            verify_output_dir=verify_output_dir,
            device=device,
            threshold=threshold,
        )
    runtime_verified = output_verification["verified"]
    status_code = output_verification["status_code"]
    ready = status_code == "ready"
    return {
        "ready": ready,
        "status_code": status_code,
        "template_configured": template_configured,
        "template_executable": template_executable,
        "command_probe_passed": template_executable,
        "runtime_verified": runtime_verified,
        "output_verified": output_verification["verified"],
        "configured": template_configured,
        "device": device,
        "threshold": threshold,
        "configuration_source": (
            ADTOF_TEMPLATE_ENV if template_configured else "default_adapter_template"
        ),
        "command_template": template,
        "required_env": [ADTOF_TEMPLATE_ENV],
        "optional_env": [
            ADTOF_CHECKPOINT_ENV,
            ADTOF_VERIFY_INPUT_ENV,
            ADTOF_VERIFY_OUTPUT_DIR_ENV,
        ],
        "checkpoint_path": checkpoint,
        "placeholders": placeholders,
        "missing_placeholders": missing_placeholders,
        "example_command": example_command,
        "executable_check": executable_check,
        "output_verification": output_verification,
        "python_module": module_status,
        "note": (
            "ADTOF ready means a configured template actually produced a parseable "
            "raw_drum.mid with note-on events. Executable template checks alone are not enough."
        ),
    }


def _musescore_runtime_check(command_statuses: dict[str, dict], *, configured_renderer: str | None) -> dict:
    available = [
        name for name in ("musescore", "mscore", "MuseScore") if command_statuses[name]["available"]
    ]
    configured_available = bool(configured_renderer and Path(configured_renderer).expanduser().exists())
    return {
        "ready": configured_available or bool(available),
        "optional_for_phase1": True,
        "available_candidates": available,
        "configured_renderer": configured_renderer,
        "configured_renderer_available": configured_available,
        "note": (
            "MusicXML generation can pass without MuseScore; "
            "PDF export requires one candidate in PATH."
        ),
    }


def _true_pipeline_missing(
    *,
    ffmpeg_ready: bool,
    demucs_ready: bool,
    adtof_ready: bool,
) -> list[str]:
    missing: list[str] = []
    if not ffmpeg_ready:
        missing.append("ffmpeg command not available")
    if not demucs_ready:
        missing.append("Demucs package/command probe is not ready")
    if not adtof_ready:
        missing.append(
            "ADTOF runtime has not produced and verified raw_drum.mid; "
            f"set {ADTOF_TEMPLATE_ENV} and {ADTOF_VERIFY_INPUT_ENV} for output verification"
        )
    return missing


def _module_status(module_name: str) -> dict:
    return {"available": importlib.util.find_spec(module_name) is not None}


def _run_probe(command: list[str], *, timeout: int) -> dict:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "exit_code": completed.returncode,
            "stdout_first_line": _first_line(completed.stdout),
            "stderr_first_line": _first_line(completed.stderr),
        }
    except FileNotFoundError as exc:
        return {"exit_code": None, "stdout_first_line": None, "stderr_first_line": str(exc)}
    except subprocess.TimeoutExpired:
        return {
            "exit_code": None,
            "stdout_first_line": None,
            "stderr_first_line": "probe timed out",
        }


def _find_placeholders(parts: list[str]) -> set[str]:
    placeholders: set[str] = set()
    for part in parts:
        for name in ("input", "output", "device", "threshold", "checkpoint"):
            if "{" + name + "}" in part:
                placeholders.add(name)
    return placeholders


def _format_adtof_template(
    parts: list[str],
    *,
    input_path: Path,
    output_path: Path,
    checkpoint: str | None,
    device: str = "cpu",
    threshold: str = "0.5",
) -> list[str]:
    replacements = {
        "input": str(input_path),
        "output": str(output_path),
        "device": device,
        "threshold": threshold,
        "checkpoint": checkpoint or "",
    }
    return [part.format(**replacements) for part in parts if part.format(**replacements)]


def _verify_adtof_output(
    parts: list[str],
    *,
    checkpoint: str | None,
    verify_input: str | None,
    verify_output_dir: str | None,
    device: str = "cpu",
    threshold: str = "0.5",
) -> dict:
    if not verify_input:
        return {
            "verified": False,
            "attempted": False,
            "status_code": "verify_input_missing",
            "reason": f"{ADTOF_VERIFY_INPUT_ENV} is not set",
        }

    input_path = Path(verify_input)
    if not input_path.exists():
        return {
            "verified": False,
            "attempted": False,
            "status_code": "verify_input_not_found",
            "reason": f"verification input does not exist: {input_path}",
        }

    output_root = Path(verify_output_dir) if verify_output_dir else None
    with tempfile.TemporaryDirectory(prefix="groovescribe-adtof-check-") as temp_dir:
        output_dir = output_root or Path(temp_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_midi_path = output_dir / "raw_drum.mid"
        command = _format_adtof_template(
            parts,
            input_path=input_path,
            output_path=raw_midi_path,
            checkpoint=checkpoint,
            device=device,
            threshold=threshold,
        )
        probe = _run_probe(command, timeout=300)
        if probe["exit_code"] != 0:
            return {
                "verified": False,
                "attempted": True,
                "status_code": "command_failed",
                "command": command,
                "output_path": str(raw_midi_path),
                "command_probe": probe,
                "reason": "ADTOF command failed",
            }
        if not raw_midi_path.exists() or raw_midi_path.stat().st_size == 0:
            return {
                "verified": False,
                "attempted": True,
                "status_code": "output_missing",
                "command": command,
                "output_path": str(raw_midi_path),
                "command_probe": probe,
                "reason": "raw_drum.mid was not created",
            }
        try:
            event_count = count_note_on_events(raw_midi_path)
        except Exception as exc:
            return {
                "verified": False,
                "attempted": True,
                "status_code": "output_unparseable",
                "command": command,
                "output_path": str(raw_midi_path),
                "command_probe": probe,
                "reason": f"raw_drum.mid is not parseable: {exc}",
            }
        return {
            "verified": event_count > 0,
            "attempted": True,
            "status_code": "ready" if event_count > 0 else "output_no_events",
            "command": command,
            "output_path": str(raw_midi_path),
            "command_probe": probe,
            "event_count": event_count,
            "reason": None if event_count > 0 else "raw_drum.mid contains no note-on events",
        }


def _verification_skipped(*, status_code: str, reason: str) -> dict:
    return {
        "verified": False,
        "attempted": False,
        "status_code": status_code,
        "reason": reason,
    }


def _command_or_module_available(command: list[str]) -> dict:
    if not command:
        return {"available": False, "reason": "empty command"}

    first = command[0]
    if first in {"python", "python3"} or Path(first).name.startswith("python"):
        if len(command) >= 3 and command[1] == "-m":
            return {
                "available": importlib.util.find_spec(command[2]) is not None,
                "type": "python_module",
                "module": command[2],
            }
        return {"available": shutil.which(first) is not None, "type": "command", "command": first}

    return {"available": shutil.which(first) is not None, "type": "command", "command": first}


def _first_line(value: str | None) -> str | None:
    if not value:
        return None
    lines = value.strip().splitlines()
    return lines[0] if lines else None


def _redact_empty(value: str | None) -> str | None:
    return value if value else None


if __name__ == "__main__":
    raise SystemExit(main())
