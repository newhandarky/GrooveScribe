from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from ai_pipeline.notation.gate_calibration import apply_gate_calibration, calibrate_gate
from ai_pipeline.benchmark.metrics import compare_drum_midi
from ai_pipeline.benchmark.provenance import validate_item_provenance
from ai_pipeline.midi.candidate_recommendation import evaluate_candidate_recommendation
from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi

try:
    from scripts.true_ai_runtime_defaults import default_adtof_command_template
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from true_ai_runtime_defaults import default_adtof_command_template


_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PYTHON = _ROOT / ".venv-ai" / "bin" / "python"
_UNSAFE = ("/Users/", "/tmp/", "/private/tmp/", "/var/folders/", "Traceback", "stdout", "stderr", "command_template")
_DEFAULT_CANDIDATE_THRESHOLDS = ("0.3", "0.4", "0.5", "0.6")
_CANDIDATE_STRATEGY_PROFILES = {
    "scalar_v1": (),
    "scalar_plus_separated_v1": ("separated_v1",),
}
_QUALITY_PROFILE = {
    "schema_version": "1.0",
    "name": "ground_truth_candidate_v1",
    "candidate_thresholds": list(_DEFAULT_CANDIDATE_THRESHOLDS),
    "selection_order": [
        "ground_truth_acceptance",
        "chart_midi_f1",
        "core_groove_accuracy",
        "mean_timing_error_ticks",
    ],
    "maximum_f1_regression": 0.02,
    "maximum_core_groove_regression": 0.02,
    "maximum_timing_error_regression_ticks": 12.0,
}
_PUBLIC_DRUM_ORDER = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_PUBLIC_DRUMS = set(_PUBLIC_DRUM_ORDER)
_PUBLIC_LICENSES = {"CC BY 4.0", "generated_synthetic", "generated_from_configured_soundfont"}
_PUBLIC_RENDERERS = {"dataset_recording", "sampled_drum_renderer", "synthetic_signal", "soundfont"}
_PUBLIC_QUALITY_FLAGS = {
    "too_few_events",
    "sparse_transcription",
    "hihat_missing_likely",
    "mostly_tom_output",
    "no_snare_detected",
    "raw_tom_dominant",
    "missing_core_groove",
    "kick_snare_only",
    "no_usable_groove",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run authorized ground-truth performance-score benchmarks")
    parser.add_argument("--manifest", type=Path, default=_env_path("GROOVESCRIBE_PERFORMANCE_BENCHMARK_MANIFEST"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=_DEFAULT_PYTHON)
    parser.add_argument(
        "--adtof-command-template",
        default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE") or default_adtof_command_template(),
    )
    parser.add_argument("--adtof-device", default="cpu")
    parser.add_argument("--demucs-model-name", default="htdemucs")
    parser.add_argument("--demucs-device", default="auto")
    parser.add_argument(
        "--adtof-threshold-preset",
        default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD_PRESET"),
    )
    parser.add_argument(
        "--tom-filter-preset",
        default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET"),
    )
    parser.add_argument(
        "--candidate-thresholds",
        default=os.environ.get("GROOVESCRIBE_CANDIDATE_THRESHOLDS", ",".join(_DEFAULT_CANDIDATE_THRESHOLDS)),
        help="Comma-separated candidate thresholds evaluated from one shared preprocessing/Demucs run.",
    )
    parser.add_argument(
        "--candidate-strategy-profile",
        choices=tuple(_CANDIDATE_STRATEGY_PROFILES),
        default=os.environ.get("GROOVESCRIBE_CANDIDATE_STRATEGY_PROFILE", "scalar_v1"),
        help="Versioned candidate family: scalar_v1 or the opt-in scalar_plus_separated_v1 experiment.",
    )
    parser.add_argument(
        "--benchmark-split",
        choices=("development", "holdout"),
        default=None,
        help="Run one manifest split. Run development before any holdout validation for an opt-in strategy.",
    )
    parser.add_argument(
        "--development-evidence-report",
        type=Path,
        default=None,
        help="Required for scalar_plus_separated_v1 holdout: matching development report with measured improvement.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Re-run every item instead of safely reusing completed matching candidate outputs.",
    )
    parser.set_defaults(resume=True)
    parser.add_argument("--mock-ai", action="store_true", help="Test-only: do not use as true-AI evidence")
    return parser.parse_args()


def run_benchmark(config: argparse.Namespace, *, process_runner=subprocess.run) -> dict[str, Any]:
    if _is_within_repo(config.output_dir):
        return _blocked_report("benchmark_output_dir_must_be_outside_repo")
    if config.manifest is not None and _is_within_repo(config.manifest):
        return _write_reports(config.output_dir, _blocked_report("benchmark_manifest_must_be_outside_repo"))
    config.output_dir.mkdir(parents=True, exist_ok=True)
    candidate_thresholds = _candidate_thresholds(getattr(config, "candidate_thresholds", None))
    if candidate_thresholds != _DEFAULT_CANDIDATE_THRESHOLDS:
        return _write_reports(config.output_dir, _blocked_report("candidate_thresholds_must_match_quality_profile"))
    if getattr(config, "adtof_threshold_preset", None):
        # Candidate analysis deliberately compares scalar thresholds. Passing a
        # class preset here would otherwise be silently removed for each
        # candidate, producing a report whose command line is semantically false.
        return _write_reports(config.output_dir, _blocked_report("candidate_threshold_preset_requires_controlled_experiment"))
    strategy_profile = _candidate_strategy_profile(getattr(config, "candidate_strategy_profile", None))
    if strategy_profile is None:
        return _write_reports(config.output_dir, _blocked_report("candidate_strategy_profile_invalid"))
    manifest = _load_manifest(config.manifest)
    if manifest is None:
        report = _skipped_report("benchmark_manifest_not_provided")
        return _write_reports(config.output_dir, report)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    requested_split = getattr(config, "benchmark_split", None)
    if requested_split is not None:
        items = [item for item in items if isinstance(item, dict) and item.get("benchmark_split") == requested_split]
    if not items:
        return _write_reports(config.output_dir, _skipped_report("benchmark_manifest_empty"))
    reservation_path, holdout_reason = _reserve_holdout_evidence(config, strategy_profile, config.manifest, requested_split)
    if holdout_reason is not None:
        return _write_reports(config.output_dir, _blocked_report(holdout_reason))

    try:
        runs: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            runs.append(_run_item(raw, config, process_runner))
        calibration = calibrate_gate(runs)
        for run in runs:
            gate = run.get("performance_gate")
            if isinstance(gate, dict):
                calibrated_gate = apply_gate_calibration(gate, calibration)
                calibrated_gate["ground_truth_verified"] = bool(run.get("ground_truth_verified"))
                run["calibrated_gate"] = _public_calibrated_gate(calibrated_gate)
                run["performance_gate"] = _public_performance_gate(gate)
        recommendation_failures = sum(
            run.get("candidate_recommendation_validation", {}).get("status") == "failed" for run in runs
        )
        reference_failures = sum(
            run.get("status") == "completed" and run.get("ground_truth_passed") is False for run in runs
        )
        measured_count = sum(run.get("ground_truth_eval", {}).get("status") == "measured" for run in runs)
        report = {
        "schema_version": "1.0",
        "status": _benchmark_status(runs, measured_count=measured_count, reference_failures=reference_failures, recommendation_failures=recommendation_failures),
        "quality_profile": {**_QUALITY_PROFILE, "candidate_strategy_profile": strategy_profile},
        "benchmark_split": requested_split,
        "manifest_sha256": _file_sha256(config.manifest),
        "ground_truth_verified": any(run.get("ground_truth_verified") is True for run in runs),
        "real_audio_verified": any(run.get("real_audio_verified") is True for run in runs),
        "synthetic_full_mix_present": any(run.get("synthetic_full_mix") is True for run in runs),
        "runs": runs,
        "gate_calibration": calibration,
        "strategy_comparison": _strategy_comparison(runs),
        "summary": {
            "run_count": len(runs),
            "measured_count": measured_count,
            "skipped_count": sum(run.get("status") == "skipped" for run in runs),
            "false_positive_count": calibration["false_positive_count"],
            "reference_failure_count": reference_failures,
            "candidate_recommendation_failure_count": recommendation_failures,
        },
        }
        written = _write_reports(config.output_dir, report)
        _finalize_holdout_reservation(reservation_path, measured_count > 0)
        return written
    except Exception:
        _finalize_holdout_reservation(reservation_path, False)
        raise


def _run_item(item: dict[str, Any], config: argparse.Namespace, process_runner) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = _path(item.get("audio_path"))
    ground_truth = _path(item.get("ground_truth_midi_path"))
    base = _public_item(item_id, item)
    provenance_reason = validate_item_provenance(item, audio, ground_truth, repository_root=_ROOT)
    if provenance_reason is not None:
        return {**base, "status": "skipped", "reason": provenance_reason, "ground_truth_verified": False, "calibration_eligible": False}
    if audio is None or ground_truth is None or not audio.exists() or not ground_truth.exists():
        return {**base, "status": "skipped", "reason": "benchmark_artifact_missing", "ground_truth_verified": False}
    output_dir = config.output_dir / "runs" / item_id
    command = [str(config.python), str(_ROOT / "scripts" / "run_local_pipeline.py"), "--input", str(audio), "--output-dir", str(output_dir), "--strict-input", "--demucs-model-name", str(getattr(config, "demucs_model_name", "htdemucs")), "--demucs-device", config.demucs_device, "--adtof-device", config.adtof_device]
    if config.mock_ai:
        command.append("--mock-ai")
    if config.adtof_command_template:
        command.extend(["--adtof-command-template", config.adtof_command_template])
    threshold_preset = getattr(config, "adtof_threshold_preset", None)
    if threshold_preset:
        command.extend(["--adtof-threshold-preset", threshold_preset])
    tom_filter_preset = getattr(config, "tom_filter_preset", None)
    if tom_filter_preset:
        command.extend(["--tom-filter-preset", tom_filter_preset])
    candidate_thresholds = _candidate_thresholds(getattr(config, "candidate_thresholds", None))
    if candidate_thresholds and not config.mock_ai:
        command.extend(["--candidate-thresholds", ",".join(candidate_thresholds)])
    candidate_presets = _CANDIDATE_STRATEGY_PROFILES[_candidate_strategy_profile(getattr(config, "candidate_strategy_profile", None)) or "scalar_v1"]
    if candidate_presets and not config.mock_ai:
        command.extend(["--candidate-threshold-presets", ",".join(candidate_presets)])
    if isinstance(item.get("tempo_bpm"), (int, float)):
        command.extend(["--tempo-bpm", str(item["tempo_bpm"])])
    pipeline = _completed_pipeline_for_resume(
        output_dir,
        strategy_profile=_candidate_strategy_profile(getattr(config, "candidate_strategy_profile", None)) or "scalar_v1",
    ) if getattr(config, "resume", True) else None
    pipeline_reused = pipeline is not None
    if pipeline is None:
        completed = process_runner(command, cwd=str(_ROOT), capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return {**base, "status": "failed", "reason": "pipeline_failed", "ground_truth_verified": False}
        pipeline = _json_file(output_dir / "logs" / "pipeline.json")
    quality = pipeline.get("quality") if isinstance(pipeline.get("quality"), dict) else {}
    gate = quality.get("performance_gate") if isinstance(quality.get("performance_gate"), dict) else {}
    acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), dict) else {}
    candidate_analysis = pipeline.get("candidate_analysis") if isinstance(pipeline.get("candidate_analysis"), dict) else {}
    candidate_evaluation = _evaluate_candidates(
        candidate_analysis,
        output_dir=output_dir,
        ground_truth=ground_truth,
        acceptance=acceptance,
    )
    canonical_id = candidate_analysis.get("canonical_candidate_id") if isinstance(candidate_analysis.get("canonical_candidate_id"), str) else None
    canonical = next(
        (candidate for candidate in candidate_evaluation["candidates"] if candidate.get("candidate_id") == canonical_id),
        None,
    )
    if canonical is not None:
        comparison = canonical["ground_truth_eval"]
        core_groove_accuracy = canonical["core_groove_accuracy"]
    else:
        comparison = compare_drum_midi(output_dir / "notation" / "performance_score.mid", ground_truth)
        core_groove_accuracy = _core_groove_accuracy(output_dir / "notation" / "chart_events.json", ground_truth)
    passed = _reference_passed(comparison, core_groove_accuracy, acceptance)
    gate["ground_truth_verified"] = comparison.get("status") == "measured"
    return {
        **base,
        "status": "completed",
        "ground_truth_verified": comparison.get("status") == "measured",
        "synthetic_full_mix": base["synthetic_full_mix"],
        "real_audio_verified": bool(comparison.get("status") == "measured" and not base["synthetic_full_mix"]),
        "ground_truth_eval": _public_ground_truth_eval(comparison),
        "ground_truth_passed": passed,
        "calibration_eligible": item.get("calibration_eligible") is True,
        "performance_gate": gate,
        "auto_gate_candidate": gate.get("uncalibrated_verdict") == "performance_ready",
        "core_groove_accuracy": _public_core_groove_accuracy(core_groove_accuracy),
        "artifacts": {"ref": f"benchmark:{item_id}", "performance_midi": True, "performance_musicxml": True},
        "candidate_evaluation": candidate_evaluation["candidates"],
        "candidate_recommendation_validation": candidate_evaluation["validation"],
        "pipeline_reused": pipeline_reused,
    }


def _completed_pipeline_for_resume(output_dir: Path, *, strategy_profile: str = "scalar_v1") -> dict[str, Any] | None:
    """Return only a complete, profile-matching result that is safe to measure again.

    A partial pipeline is never resumed at an arbitrary stage.  Re-running it is
    safer than mixing artifacts from different executions, while a completed
    four-candidate result (including an explicitly recorded failed candidate)
    can be measured again without repeating preprocessing, Demucs, or ADTOF.
    """
    pipeline = _json_file(output_dir / "logs" / "pipeline.json")
    if pipeline.get("status") != "completed":
        return None
    analysis = pipeline.get("candidate_analysis")
    candidates = analysis.get("candidates") if isinstance(analysis, dict) else None
    expected_presets = _CANDIDATE_STRATEGY_PROFILES.get(strategy_profile)
    if expected_presets is None or not isinstance(candidates, list) or len(candidates) != len(_DEFAULT_CANDIDATE_THRESHOLDS) + len(expected_presets):
        return None
    expected = {float(value) for value in _DEFAULT_CANDIDATE_THRESHOLDS}
    observed: set[float] = set()
    observed_presets: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") not in {"completed", "failed"}:
            return None
        config = candidate.get("config")
        threshold = config.get("threshold") if isinstance(config, dict) else None
        preset = config.get("adtof_threshold_preset") if isinstance(config, dict) else None
        if isinstance(threshold, (int, float)):
            observed.add(float(threshold))
        elif isinstance(preset, str) and preset in expected_presets:
            observed_presets.add(preset)
        else:
            return None
        candidate_id = _safe_id(candidate.get("candidate_id"))
        if candidate.get("status") == "completed":
            notation = output_dir / "candidates" / candidate_id / "notation"
            if not (notation / "performance_score.mid").is_file() or not (notation / "chart_events.json").is_file():
                return None
    return pipeline if observed == expected and observed_presets == set(expected_presets) else None


def _benchmark_status(
    runs: list[dict[str, Any]], *, measured_count: int, reference_failures: int, recommendation_failures: int
) -> str:
    if not runs or measured_count == 0:
        return "blocked"
    if reference_failures or recommendation_failures:
        return "failed"
    if any(run.get("status") != "completed" for run in runs):
        return "blocked"
    return "completed"


def _candidate_thresholds(value: object) -> tuple[str, ...]:
    if value is None:
        return _DEFAULT_CANDIDATE_THRESHOLDS
    if not isinstance(value, str):
        return ()
    try:
        parsed = tuple(float(item.strip()) for item in value.split(","))
    except ValueError:
        return ()
    if len(parsed) != len(_DEFAULT_CANDIDATE_THRESHOLDS) or len(set(parsed)) != len(parsed):
        return ()
    if parsed != tuple(float(item) for item in _DEFAULT_CANDIDATE_THRESHOLDS):
        return ()
    return _DEFAULT_CANDIDATE_THRESHOLDS


def _candidate_strategy_profile(value: object) -> str | None:
    profile = "scalar_v1" if value is None else value
    return profile if profile in _CANDIDATE_STRATEGY_PROFILES else None


def _holdout_evidence_reason(config: argparse.Namespace, strategy_profile: str, manifest_path: Path | None, split: object) -> str | None:
    if strategy_profile != "scalar_plus_separated_v1" or split != "holdout":
        return None
    evidence_path = getattr(config, "development_evidence_report", None)
    if not isinstance(evidence_path, Path) or _is_within_repo(evidence_path) or not evidence_path.is_file():
        return "development_evidence_required"
    evidence = _json_file(evidence_path)
    comparison = evidence.get("strategy_comparison") if isinstance(evidence.get("strategy_comparison"), dict) else {}
    quality_profile = evidence.get("quality_profile") if isinstance(evidence.get("quality_profile"), dict) else {}
    if (
        evidence.get("benchmark_split") != "development"
        or evidence.get("manifest_sha256") != _file_sha256(manifest_path)
        or quality_profile.get("candidate_strategy_profile") != strategy_profile
        or comparison.get("status") != "measured"
        or comparison.get("improved") is not True
    ):
        return "development_evidence_invalid"
    return None


def _reserve_holdout_evidence(
    config: argparse.Namespace, strategy_profile: str, manifest_path: Path | None, split: object
) -> tuple[Path | None, str | None]:
    reason = _holdout_evidence_reason(config, strategy_profile, manifest_path, split)
    if reason is not None:
        return None, reason
    if strategy_profile != "scalar_plus_separated_v1" or split != "holdout":
        return None, None
    evidence_path = getattr(config, "development_evidence_report", None)
    if not isinstance(evidence_path, Path):
        return None, "development_evidence_required"
    reservation_path = evidence_path.with_name(f"{evidence_path.stem}.holdout-reservation.json")
    consumed_path = evidence_path.with_name(f"{evidence_path.stem}.holdout-consumed.json")
    if consumed_path.exists():
        return None, "holdout_evidence_already_consumed"
    try:
        with reservation_path.open("x", encoding="utf-8") as handle:
            json.dump({"schema_version": "1.0", "status": "reserved"}, handle)
            handle.write("\n")
    except FileExistsError:
        return None, "holdout_evidence_already_consumed"
    except OSError:
        return None, "holdout_evidence_reservation_failed"
    return reservation_path, None


def _finalize_holdout_reservation(reservation_path: Path | None, measured: bool) -> None:
    if reservation_path is None:
        return
    try:
        if measured:
            reservation_path.replace(reservation_path.with_name(reservation_path.name.replace("-reservation", "-consumed")))
        elif reservation_path.exists():
            reservation_path.unlink()
    except OSError:
        # Keep the reservation in place on an ambiguous finalize failure: this
        # fails closed rather than permitting an accidental second holdout run.
        return


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strategy_comparison(runs: list[dict[str, Any]]) -> dict[str, object]:
    pairs: list[tuple[float, float]] = []
    for run in runs:
        candidates = run.get("candidate_evaluation") if isinstance(run.get("candidate_evaluation"), list) else []
        scalar = [candidate.get("ground_truth_eval", {}).get("f1") for candidate in candidates if isinstance(candidate, dict) and candidate.get("strategy") == "scalar_threshold_v1"]
        preset = next((candidate.get("ground_truth_eval", {}).get("f1") for candidate in candidates if isinstance(candidate, dict) and candidate.get("candidate_id") == "preset_separated_v1"), None)
        scalar_values = [float(value) for value in scalar if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if scalar_values and isinstance(preset, (int, float)) and not isinstance(preset, bool):
            pairs.append((max(scalar_values), float(preset)))
    if not pairs:
        return {"status": "unavailable", "scalar_macro_f1": None, "separated_macro_f1": None, "improved": False}
    scalar_macro = sum(scalar for scalar, _preset_value in pairs) / len(pairs)
    preset_macro = sum(preset for _scalar, preset in pairs) / len(pairs)
    return {"status": "measured", "scalar_macro_f1": round(scalar_macro, 4), "separated_macro_f1": round(preset_macro, 4), "improved": preset_macro > scalar_macro}


def _evaluate_candidates(
    analysis: dict[str, Any], *, output_dir: Path, ground_truth: Path, acceptance: dict
) -> dict[str, Any]:
    raw_candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    candidates = [
        _evaluate_candidate(candidate, output_dir=output_dir, ground_truth=ground_truth, acceptance=acceptance)
        for candidate in raw_candidates
        if isinstance(candidate, dict)
    ]
    measured = [candidate for candidate in candidates if candidate.get("ground_truth_eval", {}).get("status") == "measured"]
    eligible = [candidate for candidate in measured if candidate.get("eligible_for_recommendation")]
    if not raw_candidates:
        return {"candidates": [], "validation": {"status": "not_applicable", "reason": "candidate_analysis_unavailable"}}
    if not eligible:
        return {"candidates": [_public_candidate_evaluation(candidate) for candidate in candidates], "validation": {"status": "not_applicable", "reason": "no_measured_recommended_candidate"}}
    # Re-evaluate existing artifacts with the current deterministic profile. This
    # makes a resumed benchmark measure the rule that new jobs would use, rather
    # than silently trusting a recommendation serialized by an older profile.
    recommended = min(
        eligible,
        key=lambda candidate: (-int(candidate["recommendation"].get("score") or 0), int(candidate.get("_position") or 0)),
    )
    best = max(eligible, key=_candidate_quality_key)
    passed = _recommendation_is_non_regressing(recommended, best)
    return {
        "candidates": [_public_candidate_evaluation(candidate) for candidate in candidates],
        "validation": {
            "status": "passed" if passed else "failed",
            "recommended_candidate_id": recommended["candidate_id"],
            "best_candidate_id": best["candidate_id"],
            "profile": _QUALITY_PROFILE["name"],
        },
    }


def _evaluate_candidate(candidate: dict[str, Any], *, output_dir: Path, ground_truth: Path, acceptance: dict) -> dict[str, Any]:
    candidate_id = _safe_id(candidate.get("candidate_id"))
    candidate_dir = output_dir / "candidates" / candidate_id
    midi = candidate_dir / "notation" / "performance_score.mid"
    chart = candidate_dir / "notation" / "chart_events.json"
    metrics = compare_drum_midi(midi, ground_truth, round_digits=None)
    core = _core_groove_accuracy(chart, ground_truth, round_digits=None) if chart.exists() else {"status": "unavailable", "accuracy": None}
    quality = candidate.get("quality") if isinstance(candidate.get("quality"), dict) else {}
    validation = candidate.get("validation") if isinstance(candidate.get("validation"), dict) else {}
    recommendation = evaluate_candidate_recommendation(
        status="completed" if candidate.get("status") == "completed" else "failed",
        quality=quality,
        validation=validation,
    )
    return {
        "candidate_id": candidate_id,
        "_position": int(candidate.get("position") or 0),
        "threshold": _public_threshold(candidate.get("config")),
        "strategy": _public_candidate_strategy(candidate.get("config")),
        "status": "completed" if candidate.get("status") == "completed" else "failed",
        "selected": candidate.get("selected") is True,
        "eligible_for_recommendation": candidate.get("status") == "completed" and recommendation.get("rejected") is not True,
        "recommendation": _public_recommendation(recommendation),
        "processed_drum_counts": _public_counts(quality.get("processed_drum_counts")),
        "quality_flags": _public_flags(quality.get("quality_flags")),
        "notation_readability": _public_readability(quality.get("notation_readability")),
        "ground_truth_eval": _public_ground_truth_eval(metrics),
        "core_groove_accuracy": _public_core_groove_accuracy(core),
        "ground_truth_passed": _reference_passed(metrics, core, acceptance),
        "performance_gate": _public_performance_gate(quality.get("performance_gate")),
        "_raw_ground_truth_eval": metrics,
        "_raw_core_groove_accuracy": core,
    }


def _candidate_quality_key(candidate: dict[str, Any]) -> tuple[bool, float, float, float, str]:
    metrics = candidate.get("_raw_ground_truth_eval") or candidate.get("ground_truth_eval") or {}
    core = candidate.get("_raw_core_groove_accuracy") or candidate.get("core_groove_accuracy") or {}
    return (
        candidate.get("ground_truth_passed") is True,
        _metric_number(metrics.get("f1"), 0.0),
        _metric_number(core.get("accuracy"), 0.0),
        -_metric_number(metrics.get("mean_timing_error_ticks"), float("inf")),
        str(candidate.get("candidate_id")),
    )


def _recommendation_is_non_regressing(recommended: dict[str, Any], best: dict[str, Any]) -> bool:
    if recommended.get("ground_truth_passed") != best.get("ground_truth_passed"):
        return False
    recommended_metrics = recommended.get("_raw_ground_truth_eval") or recommended.get("ground_truth_eval") or {}
    best_metrics = best.get("_raw_ground_truth_eval") or best.get("ground_truth_eval") or {}
    recommended_core = recommended.get("_raw_core_groove_accuracy") or recommended.get("core_groove_accuracy") or {}
    best_core = best.get("_raw_core_groove_accuracy") or best.get("core_groove_accuracy") or {}
    return (
        _metric_number(recommended_metrics.get("f1"), 0.0) >= _metric_number(best_metrics.get("f1"), 0.0) - _QUALITY_PROFILE["maximum_f1_regression"]
        and _metric_number(recommended_core.get("accuracy"), 0.0) >= _metric_number(best_core.get("accuracy"), 0.0) - _QUALITY_PROFILE["maximum_core_groove_regression"]
        and _metric_number(recommended_metrics.get("mean_timing_error_ticks"), float("inf"))
        <= _metric_number(best_metrics.get("mean_timing_error_ticks"), float("inf")) + _QUALITY_PROFILE["maximum_timing_error_regression_ticks"]
    )


def _metric_number(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _public_threshold(config: object) -> float | None:
    if not isinstance(config, dict):
        return None
    value = config.get("threshold")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < float(value) <= 1 else None


def _public_candidate_strategy(config: object) -> str:
    source = config if isinstance(config, dict) else {}
    strategy = source.get("strategy") or source.get("threshold_strategy")
    if strategy == "scalar_threshold_v1":
        return strategy
    if strategy == "adtof_preset_v1" and source.get("adtof_threshold_preset") == "separated_v1":
        return strategy
    return "unknown"


def _public_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        drum: count
        for drum, count in sorted(value.items())
        if drum in _PUBLIC_DRUMS and isinstance(count, int) and not isinstance(count, bool) and count >= 0
    }


def _public_flags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({flag for flag in value if isinstance(flag, str) and flag in _PUBLIC_QUALITY_FLAGS})


def _public_recommendation(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    score = source.get("score")
    recommendation = source.get("recommendation")
    return {
        "score": int(score) if isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100 else None,
        "recommendation": recommendation if recommendation in {"recommended_for_practice", "reference_with_caveats", "reanalyze_recommended"} else "reanalyze_recommended",
        "rejected": source.get("rejected") is True,
    }


def _public_readability(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    integer_fields = (
        "voice_count",
        "hand_event_count",
        "foot_event_count",
        "generic_tom_count",
        "measure_count",
        "dense_measure_count",
        "dense_measure_threshold",
    )
    result = {
        field: source[field]
        for field in integer_fields
        if isinstance(source.get(field), int) and not isinstance(source[field], bool) and source[field] >= 0
    }
    result["has_hand_voice"] = source.get("has_hand_voice") is True
    result["has_foot_voice"] = source.get("has_foot_voice") is True
    result["layout_profile"] = source.get("layout_profile") if source.get("layout_profile") == "standard_drum_v1" else "unknown"
    return result


def _public_performance_gate(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    alignment = source.get("audio_alignment") if isinstance(source.get("audio_alignment"), dict) else {}
    onset = alignment.get("onset_alignment_rate")
    return {
        "verdict": source.get("verdict") if source.get("verdict") in {"performance_ready", "playable_but_low_confidence", "needs_better_source", "not_ready"} else "not_ready",
        "onset_alignment_rate": round(float(onset), 4) if isinstance(onset, (int, float)) and not isinstance(onset, bool) and 0 <= float(onset) <= 1 else None,
    }


def _public_ground_truth_eval(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    per_drum = source.get("per_drum") if isinstance(source.get("per_drum"), dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "f1": _public_unit_interval(source.get("f1")),
        "mean_timing_error_ticks": _public_nonnegative_number(source.get("mean_timing_error_ticks")),
        "per_drum": {
            drum: {"f1": _public_unit_interval(values.get("f1"))}
            for drum in _PUBLIC_DRUM_ORDER
            if isinstance(values := per_drum.get(drum), dict)
        },
    }


def _public_candidate_evaluation(value: dict[str, Any]) -> dict[str, Any]:
    """Drop internal full-precision metrics after deterministic comparisons finish."""

    return {key: item for key, item in value.items() if key not in {"_raw_ground_truth_eval", "_raw_core_groove_accuracy"}}


def _public_core_groove_accuracy(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "status": source.get("status") if source.get("status") in {"measured", "unavailable"} else "unavailable",
        "accuracy": _public_unit_interval(source.get("accuracy")),
    }


def _public_unit_interval(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return round(number, 4) if math.isfinite(number) and 0 <= number <= 1 else None


def _public_nonnegative_number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return round(number, 3) if math.isfinite(number) and number >= 0 else None


def _public_calibrated_gate(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        **_public_performance_gate(source),
        "ground_truth_verified": source.get("ground_truth_verified") is True,
        "calibration_status": source.get("calibration_status") if source.get("calibration_status") in {"applied", "not_applied"} else "not_applied",
    }


def _reference_passed(comparison: dict, core_groove_accuracy: dict, acceptance: dict) -> bool:
    minimum_f1 = acceptance.get("minimum_f1")
    maximum_error = acceptance.get("maximum_mean_timing_error_ticks")
    if not isinstance(minimum_f1, (int, float)) or comparison.get("status") != "measured":
        return False
    if float(comparison.get("f1") or 0) < float(minimum_f1):
        return False
    per_drum_thresholds = acceptance.get("minimum_per_drum_f1")
    if isinstance(per_drum_thresholds, dict):
        per_drum = comparison.get("per_drum") if isinstance(comparison.get("per_drum"), dict) else {}
        for drum, threshold in per_drum_thresholds.items():
            measured = per_drum.get(str(drum)) if isinstance(per_drum.get(str(drum)), dict) else {}
            if isinstance(threshold, (int, float)) and float(measured.get("f1") or 0) < float(threshold):
                return False
    minimum_core_groove_accuracy = acceptance.get("minimum_core_groove_accuracy")
    if isinstance(minimum_core_groove_accuracy, (int, float)):
        accuracy = core_groove_accuracy.get("accuracy")
        if core_groove_accuracy.get("status") != "measured" or not isinstance(accuracy, (int, float)):
            return False
        if accuracy < float(minimum_core_groove_accuracy):
            return False
    error = comparison.get("mean_timing_error_ticks")
    return not isinstance(maximum_error, (int, float)) or (isinstance(error, (int, float)) and error <= maximum_error)


def _core_groove_accuracy(chart_events_path: Path, ground_truth_midi: Path, *, round_digits: int | None = 3) -> dict[str, object]:
    chart = _json_file(chart_events_path)
    ticks = int(chart.get("ticks_per_beat") or 480)
    beats, beat_type = _time_signature(str(chart.get("time_signature") or "4/4"))
    measure_ticks = ticks * beats * 4 // beat_type
    try:
        ground_truth = parse_midi(ground_truth_midi)
    except Exception:
        return {"status": "unavailable", "accuracy": None}
    core = {"kick", "snare", "closed_hat", "open_hat"}
    slot_ticks = max(1, ticks // 2)
    chart_core: dict[int, set[tuple[str, int]]] = {}
    for event in chart.get("events", []):
        if isinstance(event, dict) and event.get("drum") in core:
            tick = int(event.get("tick", 0))
            measure_index = tick // measure_ticks
            slot = round((tick % measure_ticks) / slot_ticks)
            chart_core.setdefault(measure_index, set()).add((str(event["drum"]), slot))
    expected_core: dict[int, set[tuple[str, int]]] = {}
    for event in ground_truth.notes:
        mapped = map_to_general_midi_drum(event.note)
        if mapped is not None and mapped.drum in core:
            tick = round(event.tick * ticks / max(1, ground_truth.ticks_per_beat))
            measure_index = tick // measure_ticks
            slot = round((tick % measure_ticks) / slot_ticks)
            expected_core.setdefault(measure_index, set()).add((mapped.drum, slot))
    indices = set(chart_core) | set(expected_core)
    if not indices:
        return {"status": "unavailable", "accuracy": None}
    measure_scores = []
    for index in sorted(indices):
        predicted = chart_core.get(index, set())
        expected = expected_core.get(index, set())
        matches = len(predicted & expected)
        precision = matches / len(predicted) if predicted else 0.0
        recall = matches / len(expected) if expected else 0.0
        measure_scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {
        "status": "measured",
        "accuracy": sum(measure_scores) / len(measure_scores) if round_digits is None else round(sum(measure_scores) / len(measure_scores), round_digits),
        "metric": "macro_measure_core_onset_f1_eighth_grid",
        "chart_core_measure_count": len(chart_core),
        "ground_truth_core_measure_count": len(expected_core),
    }


def _time_signature(value: str) -> tuple[int, int]:
    try:
        beats_text, beat_type_text = value.split("/", 1)
        beats, beat_type = int(beats_text), int(beat_type_text)
        if beats > 0 and beat_type > 0 and beat_type & (beat_type - 1) == 0:
            return beats, beat_type
    except ValueError:
        pass
    return 4, 4


def _public_item(item_id: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item_id,
        "input_type": item.get("input_type") if item.get("input_type") in {"drum_only", "full_mix"} else "unknown",
        "tempo_bpm": _public_tempo(item.get("tempo_bpm")),
        "time_signature": _public_time_signature(item.get("time_signature")),
        "license": item.get("license") if item.get("license") in _PUBLIC_LICENSES else "unknown",
        "renderer": item.get("renderer") if item.get("renderer") in _PUBLIC_RENDERERS else "unknown",
        "calibration_eligible": item.get("calibration_eligible") is True,
        "synthetic_full_mix": item.get("synthetic_full_mix") is True,
        "real_audio_verified": False,
    }


def _public_tempo(value: object) -> float | int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    tempo = float(value)
    return round(tempo, 3) if 0 < tempo <= 400 and math.isfinite(tempo) else None


def _public_time_signature(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    try:
        numerator_text, denominator_text = value.split("/", 1)
        numerator, denominator = int(numerator_text), int(denominator_text)
    except ValueError:
        return "unknown"
    if 1 <= numerator <= 32 and denominator in {1, 2, 4, 8, 16, 32}:
        return f"{numerator}/{denominator}"
    return "unknown"


def _write_reports(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    _assert_safe(report)
    report_path = output_dir / "performance_benchmark_report.json"
    calibration_path = output_dir / "gate_calibration.json"
    csv_path = output_dir / "performance_benchmark_report.csv"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    calibration_path.write_text(json.dumps(report.get("gate_calibration") or {}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "status", "input_type", "ground_truth_verified", "overall_f1", "timing_error_ticks", "auto_gate_candidate", "calibrated_verdict"])
        writer.writeheader()
        for run in report.get("runs", []):
            evaluation = run.get("ground_truth_eval") or {}
            gate = run.get("calibrated_gate") or {}
            writer.writerow({"id": run.get("id"), "status": run.get("status"), "input_type": run.get("input_type"), "ground_truth_verified": run.get("ground_truth_verified"), "overall_f1": evaluation.get("f1"), "timing_error_ticks": evaluation.get("mean_timing_error_ticks"), "auto_gate_candidate": run.get("auto_gate_candidate"), "calibrated_verdict": gate.get("verdict")})
    return report


def _skipped_report(reason: str) -> dict[str, Any]:
    return {"schema_version": "1.0", "status": "skipped", "ground_truth_verified": False, "runs": [], "gate_calibration": calibrate_gate([]), "summary": {"reason": reason, "run_count": 0}}


def _blocked_report(reason: str) -> dict[str, Any]:
    return {"schema_version": "1.0", "status": "blocked", "ground_truth_verified": False, "runs": [], "gate_calibration": calibrate_gate([]), "summary": {"reason": reason, "run_count": 0}}


def _load_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _json_file(path)


def _json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _is_within_repo(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(_ROOT.resolve())
    except ValueError:
        return False
    return True


def _safe_id(value: object) -> str:
    raw = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark"))
    return raw.strip("-")[:80] or "benchmark"


def _assert_safe(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False)
    if any(token.lower() in text.lower() for token in _UNSAFE):
        raise RuntimeError("benchmark_report_redaction_failed")


if __name__ == "__main__":
    config = parse_args()
    report = run_benchmark(config)
    print(json.dumps({"status": report["status"], "report_name": "performance_benchmark_report.json"}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] in {"completed", "skipped"} else 1)
