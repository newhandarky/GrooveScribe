from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_TRUE_AI_SMOKE") != "1",
    reason="set RUN_TRUE_AI_SMOKE=1 to run local pipeline true-AI smoke",
)
def test_run_local_pipeline_true_ai_smoke(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fixture = repo_root / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_clean_drum_pattern.wav"
    adtof_template = os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE")
    if not adtof_template:
        pytest.skip("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE is required for true-AI smoke")

    preflight = subprocess.run(
        [sys.executable, "scripts/check_ai_runtime.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=os.environ.copy(),
    )
    if preflight.returncode != 0:
        pytest.skip("runtime preflight command failed")
    preflight_body = json.loads(preflight.stdout)
    runtime_checks = preflight_body["runtime_checks"]
    adtof = runtime_checks["adtof_pytorch"]
    if not adtof["ready"]:
        pytest.skip(f"ADTOF offline evaluation runtime is not ready: {adtof.get('status_code', 'unknown')}")

    output_dir = tmp_path / "true-ai-run"
    command = [
            sys.executable,
            "scripts/run_local_pipeline.py",
            "--input",
            str(fixture),
            "--output-dir",
            str(output_dir),
            "--export-pdf",
            "--demucs-device",
            os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"),
            "--adtof-command-template",
            adtof_template,
            "--adtof-device",
            os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"),
            "--adtof-threshold",
            os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", "0.5"),
    ]
    if os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"):
        command.extend(["--adtof-checkpoint", os.environ["GROOVESCRIBE_ADTOF_CHECKPOINT"]])

    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")),
    )

    assert completed.returncode == 0, completed.stderr
    body = json.loads(completed.stdout)
    assert body["status"] == "completed"
    assert (output_dir / "midi" / "processed_drum.mid").exists()
    assert (output_dir / "notation" / "score.musicxml").exists()
    assert (output_dir / "logs" / "pipeline.json").exists()
