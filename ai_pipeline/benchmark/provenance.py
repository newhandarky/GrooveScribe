from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

UNSAFE_TOKENS = (
    "/users/",
    "/tmp/",
    "/private/tmp/",
    "/private/var/folders/",
    "/var/folders/",
    "command_template",
    "traceback",
    "raw command",
    "git status",
    "musescore --version",
    "stderr",
    "stdout",
)


def validate_item_provenance(
    item: dict[str, Any],
    audio: Path | None,
    ground_truth: Path | None,
    *,
    repository_root: Path | None = None,
) -> str | None:
    required_text = ("id", "audio_path", "ground_truth_midi_path", "time_signature", "license", "source", "source_release", "renderer", "usage_scope")
    if any(not isinstance(item.get(field), str) or not item[field].strip() for field in required_text):
        return "benchmark_provenance_invalid"
    safe_text_fields = ("id", "time_signature", "license", "source", "source_release", "renderer", "usage_scope")
    if any(_contains_unsafe_text(item[field]) for field in safe_text_fields):
        return "benchmark_provenance_invalid"
    if not _is_finite_number(item.get("tempo_bpm")) or item["tempo_bpm"] <= 0:
        return "benchmark_provenance_invalid"
    if item.get("input_type") not in {"drum_only", "full_mix"}:
        return "benchmark_provenance_invalid"
    if not str(item["license_url"]).startswith("https://"):
        return "benchmark_provenance_invalid"
    if not isinstance(item.get("calibration_eligible"), bool) or item.get("ground_truth_verified") is not True:
        return "benchmark_provenance_invalid"
    if not isinstance(item.get("synthetic_full_mix"), bool) or not isinstance(item.get("real_audio_verified"), bool):
        return "benchmark_provenance_invalid"
    if item["synthetic_full_mix"] and item["real_audio_verified"]:
        return "benchmark_provenance_invalid"
    acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), dict) else {}
    per_drum = acceptance.get("minimum_per_drum_f1")
    if (
        not _is_unit_interval(acceptance.get("minimum_f1"))
        or not _is_unit_interval(acceptance.get("minimum_core_groove_accuracy"))
        or not _is_finite_number(acceptance.get("maximum_mean_timing_error_ticks"))
        or acceptance["maximum_mean_timing_error_ticks"] < 0
        or not isinstance(per_drum, dict)
        or not per_drum
        or not all(isinstance(drum, str) and _is_unit_interval(value) for drum, value in per_drum.items())
    ):
        return "benchmark_provenance_invalid"
    checksums = item.get("sha256") if isinstance(item.get("sha256"), dict) else {}
    if audio is None or ground_truth is None or not audio.exists() or not ground_truth.exists():
        return "benchmark_artifact_missing"
    if repository_root is not None and (_is_within(audio, repository_root) or _is_within(ground_truth, repository_root)):
        return "benchmark_artifact_must_be_outside_repo"
    if checksums.get("audio") != sha256(audio) or checksums.get("ground_truth_midi") != sha256(ground_truth):
        return "benchmark_checksum_mismatch"
    reference_drums = _optional_path(item.get("reference_drums_audio_path"))
    if reference_drums is not None:
        if not reference_drums.is_file():
            return "benchmark_artifact_missing"
        if repository_root is not None and _is_within(reference_drums, repository_root):
            return "benchmark_artifact_must_be_outside_repo"
        if checksums.get("reference_drums_audio") != sha256(reference_drums):
            return "benchmark_checksum_mismatch"
    elif "reference_drums_audio_path" in item or "reference_drums_audio" in checksums:
        return "benchmark_provenance_invalid"
    split = item.get("benchmark_split")
    if split is not None and split not in {"development", "holdout"}:
        return "benchmark_provenance_invalid"
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _optional_path(value: object) -> Path | None:
    return Path(value).expanduser() if isinstance(value, str) and value else None


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_unit_interval(value: object) -> bool:
    return _is_finite_number(value) and 0 <= float(value) <= 1


def _contains_unsafe_text(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in UNSAFE_TOKENS) or "\\" in value or value.startswith("/")
