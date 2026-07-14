from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_pipeline.benchmark.metrics import aggregate_by_input_type, compare_drum_midi
from ai_pipeline.benchmark.provenance import UNSAFE_TOKENS, validate_item_provenance
from ai_pipeline.midi import MidiPostProcessor
from ai_pipeline.midi.types import MidiPostProcessConfig
from ai_pipeline.notation import MusicXmlGenerator, NotationConfig
from ai_pipeline.notation.gate_calibration import apply_gate_calibration
from ai_pipeline.notation.performance_gate import evaluate_performance_score
from ai_pipeline.transcription.benchmark_backends import get_benchmark_backend

_UNSAFE = UNSAFE_TOKENS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a benchmark-only alternative drum transcription backend spike.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--adtof-benchmark-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--backend", default="spectral_onset_spike")
    parser.add_argument("--tom-filter-preset", default="tom_guard_v1")
    parser.add_argument("--gate-calibration", type=Path, default=None)
    return parser.parse_args()


def run_spike(config: argparse.Namespace) -> dict[str, Any]:
    backend = get_benchmark_backend(config.backend)
    if backend is None:
        return _write(config.output_dir, {"schema_version": "1.0", "status": "blocked", "backend": config.backend, "reason_code": "backend_unknown"})
    availability = backend.availability()
    if not availability.ready:
        return _write(config.output_dir, {"schema_version": "1.0", "status": "blocked", "backend": config.backend, "reason_code": availability.reason_code})
    manifest = _read(config.manifest)
    calibration_path = getattr(config, "gate_calibration", None) or config.adtof_benchmark_dir / "gate_calibration.json"
    calibration = _read(calibration_path)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    runs = [_run_item(item, config, backend, calibration) for item in items if isinstance(item, dict)]
    report = {
        "schema_version": "1.0",
        "status": "completed",
        "backend": config.backend,
        "comparison_scope": "post_demucs_transcription_only",
        "calibration_audit": _calibration_audit(calibration),
        "ground_truth_verified": any(run.get("status") == "completed" for run in runs),
        "real_audio_verified": any(run.get("real_audio_verified") is True for run in runs),
        "synthetic_full_mix_present": any(run.get("synthetic_full_mix") is True for run in runs),
        "runs": runs,
        "by_input_type": aggregate_by_input_type([{"input_type": run["input_type"], "stages": {"raw": run.get("raw_metrics", {}), "processed": run.get("processed_metrics", {}), "chart": run.get("chart_metrics", {})}, "primary_failure_stage": "unknown"} for run in runs]),
        "comparison_to_adtof": _comparison(runs),
        "integration_candidate": _is_integration_candidate(runs, _comparison(runs)),
    }
    return _write(config.output_dir, report)


def _run_item(item: dict[str, Any], config: argparse.Namespace, backend, calibration: dict[str, Any]) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    source = config.adtof_benchmark_dir / "runs" / item_id
    drums_stem = source / "stems" / "drums.wav"
    ground_truth = Path(str(item.get("ground_truth_midi_path") or ""))
    audio = Path(str(item.get("audio_path") or ""))
    base = {"id": item_id, "input_type": str(item.get("input_type") or "unknown"), "synthetic_full_mix": item.get("synthetic_full_mix") is True, "real_audio_verified": bool(item.get("ground_truth_verified") is True and item.get("synthetic_full_mix") is not True)}
    provenance_reason = validate_item_provenance(item, audio, ground_truth)
    if provenance_reason is not None or not drums_stem.exists():
        return {**base, "status": "skipped", "reason": provenance_reason or "benchmark_artifact_missing"}
    output = config.output_dir / "runs" / item_id
    raw = output / "midi" / "raw_drum.mid"
    transcription = backend.transcribe(drums_stem, raw, tempo_bpm=float(item.get("tempo_bpm") or 120.0))
    if transcription["status"] != "completed":
        return {**base, "status": "blocked", "reason": transcription.get("reason_code")}
    processed = MidiPostProcessor(MidiPostProcessConfig(tom_filter_enabled=bool(config.tom_filter_preset), tom_filter_preset=config.tom_filter_preset)).process(raw, output / "midi")
    notation = MusicXmlGenerator(NotationConfig(tempo_bpm_override=float(item.get("tempo_bpm") or 120.0))).generate(processed.drum_events_path, output / "notation")
    gate = evaluate_performance_score(chart_events_path=notation.chart_events_path, performance_midi_path=notation.performance_midi_path, performance_musicxml_path=notation.performance_musicxml_path, drums_stem_path=drums_stem, gate_calibration=calibration)
    adtof_pipeline = _read(source / "logs" / "pipeline.json")
    adtof_quality = adtof_pipeline.get("quality") if isinstance(adtof_pipeline.get("quality"), dict) else {}
    raw_adtof_gate = adtof_quality.get("performance_gate") if isinstance(adtof_quality.get("performance_gate"), dict) else {}
    adtof_gate = apply_gate_calibration(raw_adtof_gate, calibration)
    return {
        **base,
        "status": "completed",
        "raw_metrics": compare_drum_midi(raw, ground_truth),
        "processed_metrics": compare_drum_midi(processed.processed_midi_path, ground_truth),
        "chart_metrics": compare_drum_midi(notation.performance_midi_path, ground_truth),
        "adtof_chart_metrics": compare_drum_midi(source / "notation" / "performance_score.mid", ground_truth),
        "adtof_performance_gate": adtof_gate,
        "performance_gate": gate,
    }


def _comparison(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = {}
    for input_type in sorted({run["input_type"] for run in runs}):
        scoped = [run for run in runs if run["input_type"] == input_type]
        alternative_scores = [run.get("chart_metrics", {}).get("f1") for run in scoped]
        adtof_scores = [run.get("adtof_chart_metrics", {}).get("f1") for run in scoped]
        alternative = _mean(alternative_scores)
        adtof = _mean(adtof_scores)
        by_type[input_type] = {
            "run_count": len(scoped),
            "alternative_chart_f1": alternative,
            "adtof_chart_f1": adtof,
            "chart_f1_delta": round(alternative - adtof, 4) if alternative is not None and adtof is not None else None,
            "per_drum": {
                drum: _per_drum_comparison(scoped, drum)
                for drum in ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
            },
            "core_groove_f1": {
                "alternative": _core_f1(scoped, "chart_metrics"),
                "adtof": _core_f1(scoped, "adtof_chart_metrics"),
            },
            "core_fp_total": {
                "alternative": _core_fp(scoped, "chart_metrics"),
                "adtof": _core_fp(scoped, "adtof_chart_metrics"),
            },
            "gate_verdicts": {
                "alternative": _verdict_counts(scoped, "performance_gate"),
                "adtof": _verdict_counts(scoped, "adtof_performance_gate"),
            },
        }
    return by_type


def _per_drum_comparison(runs: list[dict[str, Any]], drum: str) -> dict[str, float | None]:
    alternative = _mean([run.get("chart_metrics", {}).get("per_drum", {}).get(drum, {}).get("f1") for run in runs])
    adtof = _mean([run.get("adtof_chart_metrics", {}).get("per_drum", {}).get(drum, {}).get("f1") for run in runs])
    return {"alternative_f1": alternative, "adtof_f1": adtof, "delta": round(alternative - adtof, 4) if alternative is not None and adtof is not None else None}


def _mean(values: list[object]) -> float | None:
    measured = [float(value) for value in values if isinstance(value, (int, float))]
    return round(sum(measured) / len(measured), 4) if measured else None


def _is_integration_candidate(runs: list[dict[str, Any]], comparison: dict[str, Any]) -> bool:
    if not runs or any(run.get("status") != "completed" for run in runs):
        return False
    for input_type in ("drum_only", "full_mix"):
        result = comparison.get(input_type)
        if not isinstance(result, dict) or not isinstance(result.get("chart_f1_delta"), (int, float)):
            return False
        if result["chart_f1_delta"] < 0.05:
            return False
        per_drum = result.get("per_drum") if isinstance(result.get("per_drum"), dict) else {}
        for drum in ("kick", "snare", "closed_hat"):
            delta = per_drum.get(drum, {}).get("delta") if isinstance(per_drum.get(drum), dict) else None
            if not isinstance(delta, (int, float)) or delta < 0.05:
                return False
        core = result.get("core_groove_f1") if isinstance(result.get("core_groove_f1"), dict) else {}
        if not isinstance(core.get("alternative"), (int, float)) or not isinstance(core.get("adtof"), (int, float)) or core["alternative"] < core["adtof"] + 0.05:
            return False
        fp = result.get("core_fp_total") if isinstance(result.get("core_fp_total"), dict) else {}
        if not isinstance(fp.get("alternative"), int) or not isinstance(fp.get("adtof"), int) or fp["alternative"] > fp["adtof"]:
            return False
        verdicts = result.get("gate_verdicts") if isinstance(result.get("gate_verdicts"), dict) else {}
        alternative_ready = _count(verdicts.get("alternative"), "performance_ready")
        adtof_ready = _count(verdicts.get("adtof"), "performance_ready")
        if alternative_ready > adtof_ready:
            return False
        if any(_verdict_rank(run.get("performance_gate")) < _verdict_rank(run.get("adtof_performance_gate")) for run in runs):
            return False
    return True


def _core_f1(runs: list[dict[str, Any]], metric_name: str) -> float | None:
    values = []
    for run in runs:
        per_drum = run.get(metric_name, {}).get("per_drum", {}) if isinstance(run.get(metric_name), dict) else {}
        scores = [per_drum.get(drum, {}).get("f1") for drum in ("kick", "snare", "closed_hat") if isinstance(per_drum.get(drum), dict)]
        score = _mean(scores)
        if score is not None:
            values.append(score)
    return _mean(values)


def _core_fp(runs: list[dict[str, Any]], metric_name: str) -> int:
    return sum(
        int(run.get(metric_name, {}).get("per_drum", {}).get(drum, {}).get("fp") or 0)
        for run in runs
        for drum in ("kick", "snare", "closed_hat")
        if isinstance(run.get(metric_name), dict)
    )


def _verdict_counts(runs: list[dict[str, Any]], gate_name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for run in runs:
        gate = run.get(gate_name) if isinstance(run.get(gate_name), dict) else {}
        verdict = str(gate.get("verdict") or "not_ready")
        result[verdict] = result.get(verdict, 0) + 1
    return result


def _count(value: object, key: str) -> int:
    return int(value.get(key) or 0) if isinstance(value, dict) else 0


def _calibration_audit(calibration: dict[str, Any]) -> dict[str, Any]:
    status = str(calibration.get("status") or "unavailable")
    allowed = status == "calibrated" and calibration.get("allow_performance_ready") is True
    return {
        "status": status,
        "allow_performance_ready": allowed,
        "required_onset_alignment": calibration.get("min_auto_onset_alignment") if allowed else None,
        "accepted_reference_count": int(calibration.get("accepted_reference_count") or 0),
        "accepted_input_types": [str(value) for value in calibration.get("accepted_input_types", []) if isinstance(value, str)],
        "false_positive_count": int(calibration.get("false_positive_count") or 0),
    }


def _verdict_rank(gate: object) -> int:
    verdict = str(gate.get("verdict") or "not_ready") if isinstance(gate, dict) else "not_ready"
    return {"not_ready": 0, "needs_better_source": 1, "playable_but_low_confidence": 2, "performance_ready": 3}.get(verdict, 0)


def _write(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    _assert_safe(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "alternative_backend_spike_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark")).strip("-")[:80]


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    if any(token in serialized for token in _UNSAFE):
        raise RuntimeError("alternative_backend_report_redaction_failed")


if __name__ == "__main__":
    report = run_spike(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "alternative_backend_spike_report.json"}, ensure_ascii=False))
