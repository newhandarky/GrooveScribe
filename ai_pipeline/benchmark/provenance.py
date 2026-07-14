from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

UNSAFE_TOKENS = (
    "/users/",
    "/tmp/",
    "/private/tmp/",
    "/private/var/folders/",
    "/var/folders/",
    "command_template",
    "stderr",
    "stdout",
)


def validate_item_provenance(item: dict[str, Any], audio: Path | None, ground_truth: Path | None) -> str | None:
    required_text = ("id", "audio_path", "ground_truth_midi_path", "time_signature", "license", "source", "source_release", "renderer", "usage_scope")
    if any(not isinstance(item.get(field), str) or not item[field].strip() for field in required_text):
        return "benchmark_provenance_invalid"
    if not isinstance(item.get("tempo_bpm"), (int, float)) or isinstance(item.get("tempo_bpm"), bool) or item["tempo_bpm"] <= 0:
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
        not all(isinstance(acceptance.get(field), (int, float)) and not isinstance(acceptance.get(field), bool) for field in ("minimum_f1", "minimum_core_groove_accuracy", "maximum_mean_timing_error_ticks"))
        or not isinstance(per_drum, dict)
        or not per_drum
        or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in per_drum.values())
    ):
        return "benchmark_provenance_invalid"
    checksums = item.get("sha256") if isinstance(item.get("sha256"), dict) else {}
    if audio is None or ground_truth is None or not audio.exists() or not ground_truth.exists():
        return "benchmark_artifact_missing"
    if checksums.get("audio") != sha256(audio) or checksums.get("ground_truth_midi") != sha256(ground_truth):
        return "benchmark_checksum_mismatch"
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
