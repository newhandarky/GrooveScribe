from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ai_pipeline.notation.gate_calibration import apply_gate_calibration, calibrate_gate
from ai_pipeline.benchmark.metrics import compare_drum_midi
from ai_pipeline.benchmark.provenance import validate_item_provenance
from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi


_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PYTHON = _ROOT / ".venv-ai" / "bin" / "python"
_UNSAFE = ("/Users/", "/tmp/", "/private/tmp/", "/var/folders/", "Traceback", "stdout", "stderr", "command_template")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run authorized ground-truth performance-score benchmarks")
    parser.add_argument("--manifest", type=Path, default=_env_path("GROOVESCRIBE_PERFORMANCE_BENCHMARK_MANIFEST"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=_DEFAULT_PYTHON)
    parser.add_argument(
        "--adtof-command-template",
        default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"),
    )
    parser.add_argument("--adtof-device", default="cpu")
    parser.add_argument("--demucs-device", default="auto")
    parser.add_argument(
        "--adtof-threshold-preset",
        default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD_PRESET"),
    )
    parser.add_argument(
        "--tom-filter-preset",
        default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET"),
    )
    parser.add_argument("--mock-ai", action="store_true", help="Test-only: do not use as true-AI evidence")
    return parser.parse_args()


def run_benchmark(config: argparse.Namespace, *, process_runner=subprocess.run) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(config.manifest)
    if manifest is None:
        report = _skipped_report("benchmark_manifest_not_provided")
        return _write_reports(config.output_dir, report)
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    if not items:
        return _write_reports(config.output_dir, _skipped_report("benchmark_manifest_empty"))

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
            run["calibrated_gate"] = calibrated_gate
    report = {
        "schema_version": "1.0",
        "status": "completed",
        "ground_truth_verified": any(run.get("ground_truth_verified") is True for run in runs),
        "real_audio_verified": any(run.get("real_audio_verified") is True for run in runs),
        "synthetic_full_mix_present": any(run.get("synthetic_full_mix") is True for run in runs),
        "runs": runs,
        "gate_calibration": calibration,
        "summary": {
            "run_count": len(runs),
            "measured_count": sum(run.get("ground_truth_eval", {}).get("status") == "measured" for run in runs),
            "skipped_count": sum(run.get("status") == "skipped" for run in runs),
            "false_positive_count": calibration["false_positive_count"],
        },
    }
    return _write_reports(config.output_dir, report)


def _run_item(item: dict[str, Any], config: argparse.Namespace, process_runner) -> dict[str, Any]:
    item_id = _safe_id(item.get("id"))
    audio = _path(item.get("audio_path"))
    ground_truth = _path(item.get("ground_truth_midi_path"))
    base = _public_item(item_id, item)
    provenance_reason = validate_item_provenance(item, audio, ground_truth)
    if provenance_reason is not None:
        return {**base, "status": "skipped", "reason": provenance_reason, "ground_truth_verified": False, "calibration_eligible": False}
    if audio is None or ground_truth is None or not audio.exists() or not ground_truth.exists():
        return {**base, "status": "skipped", "reason": "benchmark_artifact_missing", "ground_truth_verified": False}
    output_dir = config.output_dir / "runs" / item_id
    command = [str(config.python), str(_ROOT / "scripts" / "run_local_pipeline.py"), "--input", str(audio), "--output-dir", str(output_dir), "--strict-input", "--demucs-device", config.demucs_device, "--adtof-device", config.adtof_device]
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
    if isinstance(item.get("tempo_bpm"), (int, float)):
        command.extend(["--tempo-bpm", str(item["tempo_bpm"])])
    completed = process_runner(command, cwd=str(_ROOT), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {**base, "status": "failed", "reason": "pipeline_failed", "ground_truth_verified": False}
    pipeline = _json_file(output_dir / "logs" / "pipeline.json")
    quality = pipeline.get("quality") if isinstance(pipeline.get("quality"), dict) else {}
    gate = quality.get("performance_gate") if isinstance(quality.get("performance_gate"), dict) else {}
    comparison = compare_drum_midi(output_dir / "notation" / "performance_score.mid", ground_truth)
    core_groove_accuracy = _core_groove_accuracy(output_dir / "notation" / "chart_events.json", ground_truth)
    acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), dict) else {}
    passed = _reference_passed(comparison, core_groove_accuracy, acceptance)
    gate["ground_truth_verified"] = comparison.get("status") == "measured"
    return {
        **base,
        "status": "completed",
        "ground_truth_verified": comparison.get("status") == "measured",
        "synthetic_full_mix": base["synthetic_full_mix"],
        "real_audio_verified": bool(comparison.get("status") == "measured" and not base["synthetic_full_mix"]),
        "ground_truth_eval": comparison,
        "ground_truth_passed": passed,
        "calibration_eligible": item.get("calibration_eligible") is True,
        "performance_gate": gate,
        "auto_gate_candidate": gate.get("uncalibrated_verdict") == "performance_ready",
        "core_groove_accuracy": core_groove_accuracy,
        "artifacts": {"ref": f"benchmark:{item_id}", "performance_midi": True, "performance_musicxml": True},
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


def _core_groove_accuracy(chart_events_path: Path, ground_truth_midi: Path) -> dict[str, object]:
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
        "accuracy": round(sum(measure_scores) / len(measure_scores), 3),
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
        "input_type": str(item.get("input_type") or "unknown"),
        "tempo_bpm": item.get("tempo_bpm") if isinstance(item.get("tempo_bpm"), (int, float)) else None,
        "time_signature": str(item.get("time_signature") or "4/4"),
        "license": _safe_text(item.get("license")),
        "source": _safe_text(item.get("source")),
        "renderer": _safe_text(item.get("renderer")),
            "calibration_eligible": item.get("calibration_eligible") is True,
            "synthetic_full_mix": item.get("synthetic_full_mix") is True,
            "real_audio_verified": False,
        }


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


def _safe_id(value: object) -> str:
    raw = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "benchmark"))
    return raw.strip("-")[:80] or "benchmark"


def _safe_text(value: object) -> str | None:
    text = str(value) if value is not None else None
    return text if text and not any(token.lower() in text.lower() for token in _UNSAFE) else None




def _assert_safe(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False)
    if any(token.lower() in text.lower() for token in _UNSAFE):
        raise RuntimeError("benchmark_report_redaction_failed")


if __name__ == "__main__":
    config = parse_args()
    report = run_benchmark(config)
    print(json.dumps({"status": report["status"], "report_name": "performance_benchmark_report.json"}, ensure_ascii=False))
