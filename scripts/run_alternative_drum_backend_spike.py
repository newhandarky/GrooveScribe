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
_ROOT = Path(__file__).resolve().parents[1]


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
    if any(_is_within_repo(path) for path in (config.manifest, config.adtof_benchmark_dir, config.output_dir)):
        return _public_report(_blocked_report(config, config.backend, "benchmark_paths_must_be_outside_repo"))
    backend = get_benchmark_backend(config.backend)
    if backend is None:
        return _write(config.output_dir, _public_report(_blocked_report(config, config.backend, "backend_unknown")))
    availability = backend.availability()
    if not availability.ready:
        return _write(config.output_dir, _public_report(_blocked_report(config, config.backend, availability.reason_code, backend)))
    manifest = _read(config.manifest)
    calibration_path = getattr(config, "gate_calibration", None) or config.adtof_benchmark_dir / "gate_calibration.json"
    calibration = _read(calibration_path)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    runs = [_run_item(item, config, backend, calibration) for item in items if isinstance(item, dict)]
    comparison = _comparison(runs)
    integration_evaluation = _integration_evaluation(runs, comparison)
    report = _public_report({
        "schema_version": "1.0",
        "status": "completed",
        "backend": config.backend,
        "backend_provenance": _backend_provenance(backend),
        "comparison_scope": "post_demucs_transcription_only",
        "calibration_audit": _calibration_audit(calibration),
        "ground_truth_verified": any(run.get("status") == "completed" for run in runs),
        "real_audio_verified": any(run.get("real_audio_verified") is True for run in runs),
        "synthetic_full_mix_present": any(run.get("synthetic_full_mix") is True for run in runs),
        "runs": runs,
        "by_input_type": aggregate_by_input_type(
            [
                {
                    "input_type": run["input_type"],
                    "stages": {
                        "raw": run.get("raw_metrics", {}),
                        "processed": run.get("processed_metrics", {}),
                        "chart": run.get("chart_metrics", {}),
                    },
                    "primary_failure_stage": "unknown",
                }
                for run in runs
            ]
        ),
        "comparison_to_adtof": comparison,
        "integration_evaluation": integration_evaluation,
        "integration_candidate": integration_evaluation["status"] == "accepted",
    })
    return _write(config.output_dir, report)


def _blocked_report(config: argparse.Namespace, backend_name: str, reason_code: str | None, backend=None) -> dict[str, Any]:
    calibration_path = getattr(config, "gate_calibration", None) or config.adtof_benchmark_dir / "gate_calibration.json"
    calibration = _read(calibration_path)
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "backend": backend_name,
        "backend_provenance": _backend_provenance(backend),
        "comparison_scope": "post_demucs_transcription_only",
        "calibration_audit": _calibration_audit(calibration),
        "reason_code": reason_code or "backend_runtime_unavailable",
        "comparison_to_adtof": {},
        "integration_candidate": False,
    }


def _backend_provenance(backend) -> dict[str, str] | None:
    source = getattr(backend, "model_source", None)
    license_name = getattr(backend, "model_license", None)
    if not isinstance(source, str) or not isinstance(license_name, str):
        return None
    return {"model_source": source, "model_license": license_name}


def _run_item(item: dict[str, Any], config: argparse.Namespace, backend, calibration: dict[str, Any]) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    source = config.adtof_benchmark_dir / "runs" / item_id
    drums_stem = source / "stems" / "drums.wav"
    ground_truth = Path(str(item.get("ground_truth_midi_path") or ""))
    audio = Path(str(item.get("audio_path") or ""))
    base = {"id": item_id, "input_type": str(item.get("input_type") or "unknown"), "synthetic_full_mix": item.get("synthetic_full_mix") is True, "real_audio_verified": bool(item.get("ground_truth_verified") is True and item.get("synthetic_full_mix") is not True)}
    provenance_reason = validate_item_provenance(item, audio, ground_truth, repository_root=_ROOT)
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
    adtof_source, adtof_quality = _canonical_adtof_source(source, adtof_pipeline)
    raw_adtof_gate = adtof_quality.get("performance_gate") if isinstance(adtof_quality.get("performance_gate"), dict) else {}
    adtof_gate = apply_gate_calibration(raw_adtof_gate, calibration)
    return {
        **base,
        "status": "completed",
        "raw_metrics": compare_drum_midi(raw, ground_truth),
        "processed_metrics": compare_drum_midi(processed.processed_midi_path, ground_truth),
        "chart_metrics": compare_drum_midi(notation.performance_midi_path, ground_truth),
        "adtof_raw_metrics": compare_drum_midi(adtof_source / "midi" / "raw_drum.mid", ground_truth),
        "adtof_processed_metrics": compare_drum_midi(adtof_source / "midi" / "processed_drum.mid", ground_truth),
        "adtof_chart_metrics": compare_drum_midi(adtof_source / "notation" / "performance_score.mid", ground_truth),
        "adtof_performance_gate": adtof_gate,
        "performance_gate": gate,
    }


def _canonical_adtof_source(source: Path, pipeline: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Resolve the selected candidate without exposing its artifact paths in reports."""

    root_quality = pipeline.get("quality") if isinstance(pipeline.get("quality"), dict) else {}
    analysis = pipeline.get("candidate_analysis") if isinstance(pipeline.get("candidate_analysis"), dict) else {}
    candidate_id = analysis.get("canonical_candidate_id")
    candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    if not isinstance(candidate_id, str):
        return source, root_quality
    candidate = next(
        (
            value
            for value in candidates
            if isinstance(value, dict) and value.get("candidate_id") == candidate_id and value.get("status") == "completed"
        ),
        None,
    )
    if candidate is None:
        return source, root_quality
    quality = candidate.get("quality") if isinstance(candidate.get("quality"), dict) else root_quality
    return source / "candidates" / _safe_id(candidate_id), quality


def _comparison(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = {}
    for input_type in sorted({run["input_type"] for run in runs}):
        scoped = [run for run in runs if run["input_type"] == input_type]
        stages = {
            stage: _stage_comparison(scoped, stage)
            for stage in ("raw", "processed", "chart")
        }
        chart = stages["chart"]
        by_type[input_type] = {
            "run_count": len(scoped),
            "stages": stages,
            # Preserve these existing fields for older report consumers.
            "alternative_chart_f1": chart["alternative_f1"],
            "adtof_chart_f1": chart["adtof_f1"],
            "chart_f1_delta": chart["f1_delta"],
            "per_drum": chart["per_drum"],
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


def _stage_comparison(runs: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    alternative_name = f"{stage}_metrics"
    adtof_name = f"adtof_{stage}_metrics"
    alternative = _mean([run.get(alternative_name, {}).get("f1") for run in runs])
    adtof = _mean([run.get(adtof_name, {}).get("f1") for run in runs])
    return {
        "alternative_f1": alternative,
        "adtof_f1": adtof,
        "f1_delta": round(alternative - adtof, 4) if alternative is not None and adtof is not None else None,
        "per_drum": {
            drum: _per_drum_comparison(runs, drum, alternative_name, adtof_name)
            for drum in ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
        },
        "mean_timing_error_ticks": {
            "alternative": _mean([run.get(alternative_name, {}).get("mean_timing_error_ticks") for run in runs]),
            "adtof": _mean([run.get(adtof_name, {}).get("mean_timing_error_ticks") for run in runs]),
        },
    }


def _per_drum_comparison(
    runs: list[dict[str, Any]],
    drum: str,
    alternative_name: str = "chart_metrics",
    adtof_name: str = "adtof_chart_metrics",
) -> dict[str, float | None]:
    alternative = _mean([run.get(alternative_name, {}).get("per_drum", {}).get(drum, {}).get("f1") for run in runs])
    adtof = _mean([run.get(adtof_name, {}).get("per_drum", {}).get(drum, {}).get("f1") for run in runs])
    return {"alternative_f1": alternative, "adtof_f1": adtof, "delta": round(alternative - adtof, 4) if alternative is not None and adtof is not None else None}


def _mean(values: list[object]) -> float | None:
    measured = [float(value) for value in values if isinstance(value, (int, float))]
    return round(sum(measured) / len(measured), 4) if measured else None


def _is_integration_candidate(runs: list[dict[str, Any]], comparison: dict[str, Any]) -> bool:
    return _integration_evaluation(runs, comparison)["status"] == "accepted"


def _integration_evaluation(runs: list[dict[str, Any]], comparison: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic, report-safe reasons for accepting an integration spike."""

    reasons: list[str] = []
    if not runs:
        reasons.append("no_completed_runs")
    elif any(run.get("status") != "completed" for run in runs):
        reasons.append("incomplete_runs_present")
    for input_type in ("drum_only", "full_mix"):
        scoped_runs = [run for run in runs if run.get("input_type") == input_type]
        result = comparison.get(input_type)
        if not isinstance(result, dict) or not isinstance(result.get("chart_f1_delta"), (int, float)):
            reasons.append(f"{input_type}_metrics_missing")
            continue
        if result["chart_f1_delta"] < 0.05:
            reasons.append(f"{input_type}_chart_f1_delta_insufficient")
        per_drum = result.get("per_drum") if isinstance(result.get("per_drum"), dict) else {}
        core_improvements = 0
        for drum in ("kick", "snare", "closed_hat"):
            delta = per_drum.get(drum, {}).get("delta") if isinstance(per_drum.get(drum), dict) else None
            if isinstance(delta, (int, float)) and delta >= 0.05:
                core_improvements += 1
        if core_improvements < 2:
            reasons.append(f"{input_type}_core_drum_improvements_insufficient")
        core = result.get("core_groove_f1") if isinstance(result.get("core_groove_f1"), dict) else {}
        if not isinstance(core.get("alternative"), (int, float)) or not isinstance(core.get("adtof"), (int, float)) or core["alternative"] < core["adtof"] + 0.05:
            reasons.append(f"{input_type}_core_groove_f1_insufficient")
        fp = result.get("core_fp_total") if isinstance(result.get("core_fp_total"), dict) else {}
        if not isinstance(fp.get("alternative"), int) or not isinstance(fp.get("adtof"), int) or fp["alternative"] > fp["adtof"]:
            reasons.append(f"{input_type}_core_false_positive_regression")
        verdicts = result.get("gate_verdicts") if isinstance(result.get("gate_verdicts"), dict) else {}
        alternative_ready = _count(verdicts.get("alternative"), "performance_ready")
        adtof_ready = _count(verdicts.get("adtof"), "performance_ready")
        if alternative_ready < adtof_ready:
            reasons.append(f"{input_type}_performance_ready_regression")
        if any(
            _verdict_rank(run.get("performance_gate")) < _verdict_rank(run.get("adtof_performance_gate"))
            for run in scoped_runs
        ):
            reasons.append(f"{input_type}_performance_gate_regression")
    return {"status": "accepted" if not reasons else "rejected", "reason_codes": sorted(set(reasons))}


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
    report["redaction"] = {"status": "passed", "unsafe_token_count": 0}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "alternative_backend_spike_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


_PUBLIC_DRUMS = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_PUBLIC_VERDICTS = {"performance_ready", "playable_but_low_confidence", "needs_better_source", "not_ready"}
_PUBLIC_REASONS = {
    "backend_unknown",
    "backend_runtime_unavailable",
    "benchmark_paths_must_be_outside_repo",
    "benchmark_artifact_missing",
    "benchmark_artifact_must_be_outside_repo",
    "benchmark_checksum_mismatch",
    "benchmark_provenance_invalid",
    "librosa_runtime_unavailable",
    "magenta_onsets_frames_runtime_unavailable",
}
_PUBLIC_INTEGRATION_REASONS = {
    "no_completed_runs",
    "incomplete_runs_present",
    *{
        f"{input_type}_{suffix}"
        for input_type in ("drum_only", "full_mix")
        for suffix in (
            "metrics_missing",
            "chart_f1_delta_insufficient",
            "core_drum_improvements_insufficient",
            "core_groove_f1_insufficient",
            "core_false_positive_regression",
            "performance_ready_regression",
            "performance_gate_regression",
        )
    },
}


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Reduce the spike output to its stable public benchmark contract."""

    return {
        "schema_version": "1.0",
        "status": report.get("status") if report.get("status") in {"completed", "blocked"} else "blocked",
        "backend": report.get("backend") if report.get("backend") in {"spectral_onset_spike", "magenta_onsets_frames_drums"} else "unknown",
        "backend_provenance": _public_backend_provenance(report.get("backend_provenance")),
        "comparison_scope": "post_demucs_transcription_only",
        "ground_truth_verified": report.get("ground_truth_verified") is True,
        "real_audio_verified": report.get("real_audio_verified") is True,
        "synthetic_full_mix_present": report.get("synthetic_full_mix_present") is True,
        "runs": [_public_run(run) for run in report.get("runs", []) if isinstance(run, dict)],
        "by_input_type": _public_aggregate(report.get("by_input_type")),
        "comparison_to_adtof": _public_comparison(report.get("comparison_to_adtof")),
        "integration_evaluation": _public_integration_evaluation(report.get("integration_evaluation")),
        "integration_candidate": report.get("integration_candidate") is True,
        "calibration_audit": _public_calibration_audit(report.get("calibration_audit")),
        **({"reason_code": _public_reason(report.get("reason_code"))} if report.get("status") == "blocked" else {}),
    }


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_id(run.get("id")),
        "status": run.get("status") if run.get("status") in {"completed", "skipped", "blocked"} else "blocked",
        "input_type": run.get("input_type") if run.get("input_type") in {"drum_only", "full_mix"} else "unknown",
        "synthetic_full_mix": run.get("synthetic_full_mix") is True,
        "real_audio_verified": run.get("real_audio_verified") is True,
        "raw_metrics": _public_metrics(run.get("raw_metrics")),
        "processed_metrics": _public_metrics(run.get("processed_metrics")),
        "chart_metrics": _public_metrics(run.get("chart_metrics")),
        "adtof_raw_metrics": _public_metrics(run.get("adtof_raw_metrics")),
        "adtof_processed_metrics": _public_metrics(run.get("adtof_processed_metrics")),
        "adtof_chart_metrics": _public_metrics(run.get("adtof_chart_metrics")),
        "performance_gate": _public_gate(run.get("performance_gate")),
        "adtof_performance_gate": _public_gate(run.get("adtof_performance_gate")),
        **({"reason": _public_reason(run.get("reason"))} if run.get("status") != "completed" else {}),
    }


def _public_backend_provenance(value: object) -> dict[str, str] | None:
    source = value if isinstance(value, dict) else {}
    pair = (source.get("model_source"), source.get("model_license"))
    allowed = {
        ("spectral_onset_v1", "implementation_internal"),
        ("magenta_onsets_frames_e_gmd", "Apache-2.0"),
    }
    return {"model_source": pair[0], "model_license": pair[1]} if pair in allowed else None


def _public_metrics(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    per_drum = source.get("per_drum") if isinstance(source.get("per_drum"), dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "f1": _public_number(source.get("f1"), 0, 1),
        "mean_timing_error_ticks": _public_number(source.get("mean_timing_error_ticks"), 0, None),
        "per_drum": {
            drum: {
                "f1": _public_number(values.get("f1"), 0, 1),
                "fp": int(values.get("fp")) if isinstance(values.get("fp"), int) and values.get("fp") >= 0 else 0,
            }
            for drum in _PUBLIC_DRUMS
            if isinstance(values := per_drum.get(drum), dict)
        },
    }


def _public_gate(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    alignment = source.get("audio_alignment") if isinstance(source.get("audio_alignment"), dict) else {}
    return {"verdict": source.get("verdict") if source.get("verdict") in _PUBLIC_VERDICTS else "not_ready", "onset_alignment_rate": _public_number(alignment.get("onset_alignment_rate"), 0, 1)}


def _public_comparison(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        input_type: {
            "run_count": int(result.get("run_count")) if isinstance(result.get("run_count"), int) and result.get("run_count") >= 0 else 0,
            "chart_f1_delta": _public_number(result.get("chart_f1_delta"), -1, 1),
            "core_groove_f1": {name: _public_number((result.get("core_groove_f1") or {}).get(name), 0, 1) for name in ("alternative", "adtof")},
            "core_fp_total": {name: int((result.get("core_fp_total") or {}).get(name) or 0) for name in ("alternative", "adtof")},
            "gate_verdicts": {name: _public_verdict_counts((result.get("gate_verdicts") or {}).get(name)) for name in ("alternative", "adtof")},
        }
        for input_type in ("drum_only", "full_mix")
        if isinstance(result := source.get(input_type), dict)
    }


def _public_aggregate(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {input_type: {"item_count": int(result.get("item_count") or 0), "stage_f1": {stage: _public_number((result.get("stage_f1") or {}).get(stage), 0, 1) for stage in ("raw", "processed", "chart")}} for input_type in ("drum_only", "full_mix") if isinstance(result := source.get(input_type), dict)}


def _public_integration_evaluation(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {"status": source.get("status") if source.get("status") in {"accepted", "rejected"} else "rejected", "reason_codes": sorted(code for code in source.get("reason_codes", []) if code in _PUBLIC_INTEGRATION_REASONS)}


def _public_calibration_audit(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {"status": source.get("status") if source.get("status") in {"calibrated", "insufficient_evidence", "unavailable"} else "unavailable", "allow_performance_ready": source.get("allow_performance_ready") is True, "required_onset_alignment": _public_number(source.get("required_onset_alignment"), 0, 1), "accepted_reference_count": int(source.get("accepted_reference_count") or 0), "false_positive_count": int(source.get("false_positive_count") or 0)}


def _public_verdict_counts(value: object) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {verdict: int(source.get(verdict) or 0) for verdict in sorted(_PUBLIC_VERDICTS)}


def _public_reason(value: object) -> str:
    return value if value in _PUBLIC_REASONS else "backend_runtime_unavailable"


def _public_number(value: object, minimum: float, maximum: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if number < minimum or (maximum is not None and number > maximum):
        return None
    return round(number, 4)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_within_repo(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == _ROOT or _ROOT in resolved.parents


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark")).strip("-")[:80]


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    if any(token in serialized for token in _UNSAFE):
        raise RuntimeError("alternative_backend_report_redaction_failed")


if __name__ == "__main__":
    report = run_spike(parse_args())
    print(json.dumps({"status": report["status"], "report_name": "alternative_backend_spike_report.json"}, ensure_ascii=False))
