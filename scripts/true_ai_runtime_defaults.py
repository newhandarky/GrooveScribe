from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADTOF_VERIFY_INPUT = Path("/tmp/groovescribe-stems/drums.wav")
DEFAULT_ADTOF_VERIFY_OUTPUT_DIR = Path("/tmp/groovescribe-adtof-verify")
DEFAULT_DEMUCS_DEVICE = "cpu"
DEFAULT_ADTOF_DEVICE = "cpu"
DEFAULT_ADTOF_THRESHOLD = "0.5"
DEFAULT_THRESHOLD_MATRIX = ("0.3", "0.4", "0.5", "0.6")
DEFAULT_THRESHOLD_PRESET = "separated_v1"
DEFAULT_TOM_FILTER_PRESET = "tom_guard_v1"


def default_adtof_command_template(repo_root: Path = REPO_ROOT) -> str:
    return (
        f"{repo_root / '.venv-ai' / 'bin' / 'adtof'} "
        "--audio {input} --out {output} --device {device} --threshold {threshold}"
    )


def true_ai_runtime_env(
    *,
    repo_root: Path = REPO_ROOT,
    adtof_command_template: str | None = None,
    verify_input: Path = DEFAULT_ADTOF_VERIFY_INPUT,
    verify_output_dir: Path = DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
    demucs_device: str = DEFAULT_DEMUCS_DEVICE,
    adtof_device: str = DEFAULT_ADTOF_DEVICE,
    adtof_threshold: str = DEFAULT_ADTOF_THRESHOLD,
) -> dict[str, str]:
    return {
        "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE": adtof_command_template
        or default_adtof_command_template(repo_root),
        "GROOVESCRIBE_ADTOF_VERIFY_INPUT": str(verify_input),
        "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR": str(verify_output_dir),
        "GROOVESCRIBE_DEMUCS_DEVICE": demucs_device,
        "GROOVESCRIBE_ADTOF_DEVICE": adtof_device,
        "GROOVESCRIBE_ADTOF_THRESHOLD": adtof_threshold,
        "GROOVESCRIBE_ADTOF_THRESHOLD_PRESET": DEFAULT_THRESHOLD_PRESET,
        "GROOVESCRIBE_TOM_FILTER_PRESET": DEFAULT_TOM_FILTER_PRESET,
    }


def public_env_summary(env: dict[str, str]) -> dict[str, str]:
    return {
        "adtof_template": "configured" if env.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE") else "missing",
        "adtof_verify_input": "configured" if env.get("GROOVESCRIBE_ADTOF_VERIFY_INPUT") else "missing",
        "adtof_verify_output_dir": "configured" if env.get("GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR") else "missing",
        "demucs_device": env.get("GROOVESCRIBE_DEMUCS_DEVICE", DEFAULT_DEMUCS_DEVICE),
        "adtof_device": env.get("GROOVESCRIBE_ADTOF_DEVICE", DEFAULT_ADTOF_DEVICE),
        "adtof_threshold": env.get("GROOVESCRIBE_ADTOF_THRESHOLD", DEFAULT_ADTOF_THRESHOLD),
        "threshold_preset": env.get("GROOVESCRIBE_ADTOF_THRESHOLD_PRESET", DEFAULT_THRESHOLD_PRESET),
        "tom_filter_preset": env.get("GROOVESCRIBE_TOM_FILTER_PRESET", DEFAULT_TOM_FILTER_PRESET),
    }
