from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

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
COMMANDS = ["ffmpeg", "musescore", "mscore"]


def main() -> int:
    payload = {
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
        "commands": {name: _command_status(name) for name in COMMANDS},
        "python_packages": {name: _package_status(name) for name in PYTHON_PACKAGES},
        "smoke_commands": {
            "ffmpeg": "ffmpeg -version",
            "demucs": "python -m demucs --help",
            "local_pipeline_mock": "PYTHONPATH=. python scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai",
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


if __name__ == "__main__":
    raise SystemExit(main())
