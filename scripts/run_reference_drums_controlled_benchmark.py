from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ai_pipeline.benchmark.metrics import DRUMS, compare_drum_midi
from ai_pipeline.benchmark.provenance import UNSAFE_TOKENS, validate_item_provenance
from ai_pipeline.transcription.adtof import AdtofDrumTranscriber, resolve_class_thresholds

try:
    from scripts.true_ai_runtime_defaults import default_adtof_command_template
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from true_ai_runtime_defaults import default_adtof_command_template


_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_REASONS = {
    "benchmark_paths_must_be_outside_repo",
    "benchmark_provenance_invalid",
    "benchmark_artifact_must_be_outside_repo",
    "benchmark_checksum_mismatch",
    "benchmark_artifact_missing",
    "reference_drums_audio_unavailable",
    "reference_transcription_failed",
    "demucs_candidate_artifact_missing",
    "holdout_insufficient",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare reference drums -> ADTOF against full mix -> Demucs -> ADTOF.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.3, choices=(0.3, 0.4, 0.5, 0.6))
    parser.add_argument("--adtof-threshold-preset", default=None, help="Optional ADTOF per-class preset for a controlled opt-in experiment.")
    parser.add_argument("--benchmark-split", choices=("all", "development", "holdout"), default="all")
    parser.add_argument("--adtof-command-template", default=default_adtof_command_template())
    parser.add_argument("--adtof-device", default="cpu")
    parser.add_argument("--adtof-timeout-seconds", type=int, default=1_800)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def run_controlled_benchmark(config: argparse.Namespace) -> dict[str, Any]:
    paths = (config.manifest, config.benchmark_dir, config.output_dir)
    if any(_is_within_repo(path) for path in paths):
        return _write_report(config.output_dir, _blocked_report("benchmark_paths_must_be_outside_repo"))
    manifest = _read_json(config.manifest)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    rows = [
        _run_item(item, config)
        for item in items
        if isinstance(item, dict)
        and item.get("input_type") == "full_mix"
        and (getattr(config, "benchmark_split", "all") == "all" or item.get("benchmark_split") == getattr(config, "benchmark_split", "all"))
    ]
    report = {
        "schema_version": "1.0",
        "status": "completed" if rows else "skipped",
        "threshold": float(config.threshold),
        "threshold_preset": _preset(getattr(config, "adtof_threshold_preset", None)),
        "items": rows,
        "by_split": _aggregate_by_split(rows),
        "experiment_decision": _experiment_decision(rows),
        "summary": {
            "item_count": len(rows),
            "measured_item_count": sum(row.get("status") == "measured" for row in rows),
        },
    }
    public = _public_report(report)
    _assert_safe(public)
    return _write_report(config.output_dir, public)


def _run_item(item: dict[str, Any], config: argparse.Namespace) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = _path(item.get("audio_path"))
    truth = _path(item.get("ground_truth_midi_path"))
    reference_audio = _path(item.get("reference_drums_audio_path"))
    base = {"id": item_id, "benchmark_split": _split(item.get("benchmark_split"))}
    reason = validate_item_provenance(item, audio, truth, repository_root=_ROOT)
    if reason is not None or truth is None:
        return {**base, "status": "skipped", "reason": reason or "benchmark_provenance_invalid"}
    if reference_audio is None or not reference_audio.is_file():
        return {**base, "status": "skipped", "reason": "reference_drums_audio_unavailable"}
    candidate_id = _candidate_id(config.threshold, getattr(config, "adtof_threshold_preset", None))
    demucs_raw = _candidate_raw_midi(config.benchmark_dir, item_id, candidate_id)
    if demucs_raw is None:
        return {**base, "status": "skipped", "reason": "demucs_candidate_artifact_missing"}
    # Keep reference ADTOF outputs partitioned by exactly the same strategy as
    # the full-mix candidate. Reusing a scalar output for a preset comparison
    # would incorrectly attribute an ADTOF difference to Demucs.
    reference_raw = config.output_dir / "items" / item_id / "reference_drums_adtof" / candidate_id / "raw_drum.mid"
    if config.no_resume or not reference_raw.is_file():
        try:
            transcriber = AdtofDrumTranscriber.from_command_template_string(
                config.adtof_command_template,
                device=config.adtof_device,
                threshold=float(config.threshold),
                class_thresholds=resolve_class_thresholds(preset=getattr(config, "adtof_threshold_preset", None)),
                timeout_seconds=config.adtof_timeout_seconds,
            )
            transcriber.transcribe(reference_audio, reference_raw.parent)
        except Exception:
            return {**base, "status": "skipped", "reason": "reference_transcription_failed"}
    reference_metrics = compare_drum_midi(reference_raw, truth)
    demucs_metrics = compare_drum_midi(demucs_raw, truth)
    if reference_metrics.get("status") != "measured" or demucs_metrics.get("status") != "measured":
        return {**base, "status": "skipped", "reason": "benchmark_artifact_missing"}
    return {
        **base,
        "status": "measured",
        "reason": None,
        "reference_drums_adtof": reference_metrics,
        "full_mix_demucs_adtof": demucs_metrics,
        "separation_delta_f1": _delta(demucs_metrics.get("f1"), reference_metrics.get("f1")),
        "demucs_snr_db": _snr_db(reference_audio, _demucs_stem(config.benchmark_dir, item_id)),
    }


def _candidate_raw_midi(benchmark_dir: Path, item_id: str, candidate_id: str) -> Path | None:
    path = benchmark_dir / "runs" / item_id / "candidates" / candidate_id / "midi" / "raw_drum.mid"
    return path if path.is_file() else None


def _candidate_id(threshold: float, preset: object) -> str:
    """Return the exact strategy artifact paired with the reference ADTOF run."""

    return "preset_separated_v1" if _preset(preset) == "separated_v1" else f"threshold_{str(threshold).replace('.', '_')}"


def _demucs_stem(benchmark_dir: Path, item_id: str) -> Path | None:
    path = benchmark_dir / "runs" / item_id / "stems" / "drums.wav"
    return path if path.is_file() else None


def _snr_db(reference_audio: Path, demucs_audio: Path | None) -> float | None:
    if demucs_audio is None:
        return None
    try:
        import librosa
        import numpy as np

        reference, sample_rate = librosa.load(str(reference_audio), sr=None, mono=True)
        predicted, _ = librosa.load(str(demucs_audio), sr=sample_rate, mono=True)
        length = min(len(reference), len(predicted))
        if length < sample_rate // 2:
            return None
        signal = float(np.mean(np.square(reference[:length])))
        error = float(np.mean(np.square(reference[:length] - predicted[:length])))
        if signal <= 0 or error <= 0:
            return None
        return round(10 * math.log10(signal / error), 4)
    except Exception:
        return None


def _aggregate_by_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for split in ("development", "holdout"):
        measured = [row for row in rows if row.get("benchmark_split") == split and row.get("status") == "measured"]
        result[split] = {
            "item_count": sum(row.get("benchmark_split") == split for row in rows),
            "measured_count": len(measured),
            "reference_drums_adtof_f1": _mean(row.get("reference_drums_adtof", {}).get("f1") for row in measured),
            "full_mix_demucs_adtof_f1": _mean(row.get("full_mix_demucs_adtof", {}).get("f1") for row in measured),
            "separation_delta_f1": _mean(row.get("separation_delta_f1") for row in measured),
            "demucs_snr_db": _mean(row.get("demucs_snr_db") for row in measured),
        }
    return result


def _experiment_decision(rows: list[dict[str, Any]]) -> dict[str, str]:
    development = _aggregate_by_split(rows)["development"]
    holdout = _aggregate_by_split(rows)["holdout"]
    if not development["measured_count"] or not holdout["measured_count"]:
        return {"status": "not_selected", "reason": "holdout_insufficient"}
    reference_f1 = development["reference_drums_adtof_f1"]
    separation_delta = development["separation_delta_f1"]
    if isinstance(reference_f1, float) and reference_f1 < 0.35:
        return {"status": "adtof_preset_selected", "reason": "reference_drums_transcription_limited"}
    if isinstance(separation_delta, float) and separation_delta <= -0.08:
        return {"status": "demucs_backend_selected", "reason": "separation_loss_detected"}
    return {"status": "not_selected", "reason": "evidence_inconclusive"}


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": report.get("status") if report.get("status") in {"completed", "skipped", "blocked"} else "blocked",
        "threshold": _number(report.get("threshold"), 0, 1),
        "threshold_preset": _preset(report.get("threshold_preset")),
        "items": [_public_item(row) for row in report.get("items", []) if isinstance(row, dict)],
        "by_split": {split: _public_aggregate((report.get("by_split") or {}).get(split)) for split in ("development", "holdout")},
        "experiment_decision": _public_decision(report.get("experiment_decision")),
        "summary": {key: int((report.get("summary") or {}).get(key) or 0) for key in ("item_count", "measured_item_count")},
    }


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_id(row.get("id")),
        "benchmark_split": _split(row.get("benchmark_split")),
        "status": row.get("status") if row.get("status") in {"measured", "skipped"} else "skipped",
        "reason": row.get("reason") if row.get("reason") in _PUBLIC_REASONS else None,
        "reference_drums_adtof": _public_metrics(row.get("reference_drums_adtof")),
        "full_mix_demucs_adtof": _public_metrics(row.get("full_mix_demucs_adtof")),
        "separation_delta_f1": _number(row.get("separation_delta_f1"), -1, 1),
        "demucs_snr_db": _number(row.get("demucs_snr_db"), -200, 200),
    }


def _public_metrics(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    drums = source.get("per_drum") if isinstance(source.get("per_drum"), dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "f1": _number(source.get("f1"), 0, 1),
        "mean_timing_error_ticks": _number(source.get("mean_timing_error_ticks"), 0, None),
        "per_drum": {drum: {key: _number(metric.get(key), 0, 1) for key in ("precision", "recall", "f1")} for drum in DRUMS if isinstance(metric := drums.get(drum), dict)},
    }


def _public_aggregate(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "item_count": int(source.get("item_count") or 0),
        "measured_count": int(source.get("measured_count") or 0),
        "reference_drums_adtof_f1": _number(source.get("reference_drums_adtof_f1"), 0, 1),
        "full_mix_demucs_adtof_f1": _number(source.get("full_mix_demucs_adtof_f1"), 0, 1),
        "separation_delta_f1": _number(source.get("separation_delta_f1"), -1, 1),
        "demucs_snr_db": _number(source.get("demucs_snr_db"), -200, 200),
    }


def _public_decision(value: object) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    status = source.get("status")
    reason = source.get("reason")
    return {
        "status": status if status in {"adtof_preset_selected", "demucs_backend_selected", "not_selected"} else "not_selected",
        "reason": reason if reason in {"reference_drums_transcription_limited", "separation_loss_detected", "holdout_insufficient", "evidence_inconclusive"} else "evidence_inconclusive",
    }


def _blocked_report(reason: str) -> dict[str, Any]:
    return _public_report({"status": "blocked", "experiment_decision": {"reason": reason}})


def _write_report(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    if not _is_within_repo(output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "reference_drums_controlled_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _path(value: object) -> Path | None:
    return Path(value).expanduser() if isinstance(value, str) and value else None


def _split(value: object) -> str | None:
    return value if value in {"development", "holdout"} else None


def _preset(value: object) -> str | None:
    return value if value in {"separated_v1"} else None


def _delta(left: object, right: object) -> float | None:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    return round(float(left) - float(right), 4)


def _mean(values) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]
    return round(sum(numbers) / len(numbers), 4) if numbers else None


def _number(value: object, minimum: float, maximum: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    number = float(value)
    return round(number, 4) if number >= minimum and (maximum is None or number <= maximum) else None


def _is_within_repo(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == _ROOT or _ROOT in resolved.parents


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark")).strip("-")[:80]


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    if any(token.lower() in serialized for token in UNSAFE_TOKENS):
        raise RuntimeError("reference_drums_report_redaction_failed")


if __name__ == "__main__":
    report = run_controlled_benchmark(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "reference_drums_controlled_report.json"}, ensure_ascii=False))
