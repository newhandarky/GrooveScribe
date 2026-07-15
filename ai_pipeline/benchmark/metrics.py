from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi

DRUMS = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_TOLERANCE_TICKS = 60
BENCHMARK_TAXONOMY = "benchmark_6_class_v1"
_MAX_AUDIT_OFFSET_TICKS = 120
_AUDIT_OFFSET_STEP_TICKS = 10


def compare_drum_midi(
    predicted_path: Path,
    ground_truth_path: Path,
    *,
    timing_offset_ticks: int = 0,
) -> dict[str, Any]:
    """Compare normalized drum onsets on a shared 480-PPQ timing grid.

    This benchmark-only taxonomy folds pedal hi-hat into closed hi-hat. It never
    changes pipeline MIDI artifacts or product drum mappings.
    """
    try:
        predicted, predicted_source_counts, predicted_unsupported = _mapped_onsets(predicted_path)
        expected, expected_source_counts, expected_unsupported = _mapped_onsets(ground_truth_path)
    except Exception:
        return {"status": "unavailable", "per_drum": {}, "f1": None, "mean_timing_error_ticks": None}

    if timing_offset_ticks:
        predicted = {drum: [tick + timing_offset_ticks for tick in ticks] for drum, ticks in predicted.items()}

    per_drum = {}
    all_errors: list[float] = []
    for drum in DRUMS:
        matched, errors = _match(predicted[drum], expected[drum])
        tp = len(matched)
        fp = len(predicted[drum]) - tp
        fn = len(expected[drum]) - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_drum[drum] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "mean_timing_error_ticks": round(sum(errors) / len(errors), 3) if errors else None,
        }
        all_errors.extend(errors)
    scored_drums = [
        drum
        for drum in DRUMS
        if predicted[drum] or expected[drum]
    ]
    macro_f1 = sum(per_drum[drum]["f1"] for drum in scored_drums) / len(scored_drums) if scored_drums else 0.0
    return {
        "status": "measured",
        "taxonomy": {
            "name": BENCHMARK_TAXONOMY,
            "normalizations": {"pedal_hat": "closed_hat"},
            "predicted_source_counts": predicted_source_counts,
            "ground_truth_source_counts": expected_source_counts,
            "predicted_unsupported_event_count": predicted_unsupported,
            "ground_truth_unsupported_event_count": expected_unsupported,
        },
        "timing_offset_ticks": timing_offset_ticks,
        "per_drum": per_drum,
        "f1": round(macro_f1, 4),
        "scored_drum_classes": scored_drums,
        "excluded_empty_drum_classes": [drum for drum in DRUMS if drum not in scored_drums],
        "mean_timing_error_ticks": round(sum(all_errors) / len(all_errors), 3) if all_errors else None,
        "confusion_matrix": _confusion_matrix(predicted, expected),
    }


def audit_drum_midi_contract(predicted_path: Path, ground_truth_path: Path) -> dict[str, Any]:
    """Audit taxonomy and bounded global timing offset without changing scoring.

    The corrected metric is diagnostic only. Calibration and product gates must
    continue to consume their existing uncorrected evidence.
    """
    uncorrected = compare_drum_midi(predicted_path, ground_truth_path)
    if uncorrected.get("status") != "measured":
        return {
            "status": "unavailable",
            "taxonomy": BENCHMARK_TAXONOMY,
            "uncorrected": uncorrected,
            "offset_corrected": uncorrected,
            "global_timing_offset": {"status": "unavailable"},
        }

    candidates = [
        compare_drum_midi(predicted_path, ground_truth_path, timing_offset_ticks=offset)
        for offset in range(-_MAX_AUDIT_OFFSET_TICKS, _MAX_AUDIT_OFFSET_TICKS + 1, _AUDIT_OFFSET_STEP_TICKS)
    ]
    best = max(candidates, key=_audit_score)
    return {
        "status": "measured",
        "taxonomy": BENCHMARK_TAXONOMY,
        "uncorrected": uncorrected,
        "offset_corrected": best,
        "global_timing_offset": {
            "status": "measured",
            "best_offset_ticks": best["timing_offset_ticks"],
            "max_abs_offset_ticks": _MAX_AUDIT_OFFSET_TICKS,
            "step_ticks": _AUDIT_OFFSET_STEP_TICKS,
            "f1_delta": round(float(best["f1"]) - float(uncorrected["f1"]), 4),
        },
    }


def primary_failure_stage(stage_metrics: dict[str, dict[str, Any]]) -> str:
    """Attribute material F1 loss conservatively; never infer a source cause from missing data."""
    raw = _f1(stage_metrics.get("raw"))
    processed = _f1(stage_metrics.get("processed"))
    chart = _f1(stage_metrics.get("chart"))
    if raw is None or processed is None or chart is None:
        return "unknown"
    if processed + 0.08 < raw:
        return "postprocessor"
    if chart + 0.08 < processed:
        return "chart_arranger"
    timing = stage_metrics.get("raw", {}).get("mean_timing_error_ticks")
    if isinstance(timing, (int, float)) and timing > _TOLERANCE_TICKS:
        return "timing_alignment"
    if raw < 0.45:
        return "demucs_or_raw_model"
    return "unknown"


def aggregate_by_input_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for input_type in sorted({str(row.get("input_type") or "unknown") for row in rows}):
        scoped = [row for row in rows if str(row.get("input_type") or "unknown") == input_type]
        result[input_type] = {
            "item_count": len(scoped),
            "stage_f1": {
                stage: _mean([_f1(row.get("stages", {}).get(stage)) for row in scoped])
                for stage in ("raw", "processed", "chart")
            },
            "per_stage_per_drum": {
                stage: _aggregate_per_drum([row.get("stages", {}).get(stage) for row in scoped])
                for stage in ("raw", "processed", "chart")
            },
            "primary_failure_stages": _counts([str(row.get("primary_failure_stage")) for row in scoped]),
        }
    return result


def _mapped_onsets(path: Path) -> tuple[dict[str, list[float]], dict[str, int], int]:
    parsed = parse_midi(path)
    scale = 480.0 / max(1, parsed.ticks_per_beat)
    result: dict[str, list[float]] = defaultdict(list)
    source_counts: dict[str, int] = defaultdict(int)
    unsupported = 0
    for note in parsed.notes:
        mapping = map_to_general_midi_drum(note.note)
        if mapping is None:
            unsupported += 1
            continue
        source_counts[mapping.drum] += 1
        drum = "closed_hat" if mapping.drum == "pedal_hat" else mapping.drum
        if drum in DRUMS:
            result[drum].append(note.tick * scale)
        else:
            unsupported += 1
    return {drum: sorted(result[drum]) for drum in DRUMS}, dict(sorted(source_counts.items())), unsupported


def _match(predicted: list[float], expected: list[float]) -> tuple[list[tuple[float, float]], list[float]]:
    unmatched = set(range(len(expected)))
    matched: list[tuple[float, float]] = []
    errors: list[float] = []
    for onset in predicted:
        candidates = [index for index in unmatched if abs(expected[index] - onset) <= _TOLERANCE_TICKS]
        if not candidates:
            continue
        index = min(candidates, key=lambda item: abs(expected[item] - onset))
        unmatched.remove(index)
        matched.append((onset, expected[index]))
        errors.append(abs(expected[index] - onset))
    return matched, errors


def _confusion_matrix(predicted: dict[str, list[float]], expected: dict[str, list[float]]) -> dict[str, dict[str, int]]:
    """Show class substitutions within the same timing tolerance for diagnosis."""
    expected_events = [(tick, drum) for drum in DRUMS for tick in expected[drum]]
    unmatched = set(range(len(expected_events)))
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for predicted_tick, predicted_drum in sorted((tick, drum) for drum in DRUMS for tick in predicted[drum]):
        candidates = [
            index
            for index in unmatched
            if abs(expected_events[index][0] - predicted_tick) <= _TOLERANCE_TICKS
        ]
        if not candidates:
            matrix["unmatched_ground_truth"][predicted_drum] += 1
            continue
        index = min(
            candidates,
            key=lambda item: (
                abs(expected_events[item][0] - predicted_tick),
                expected_events[item][1] != predicted_drum,
            ),
        )
        unmatched.remove(index)
        matrix[expected_events[index][1]][predicted_drum] += 1
    for index in unmatched:
        _, expected_drum = expected_events[index]
        matrix[expected_drum]["unmatched_prediction"] += 1
    return {source: dict(sorted(targets.items())) for source, targets in sorted(matrix.items())}


def _audit_score(metric: dict[str, Any]) -> tuple[float, int, float, int]:
    per_drum = metric.get("per_drum") if isinstance(metric.get("per_drum"), dict) else {}
    true_positives = sum(int(value.get("tp") or 0) for value in per_drum.values() if isinstance(value, dict))
    timing_error = metric.get("mean_timing_error_ticks")
    offset = int(metric.get("timing_offset_ticks") or 0)
    return (
        float(metric.get("f1") or 0.0),
        true_positives,
        -float(timing_error) if isinstance(timing_error, (int, float)) else float("-inf"),
        -abs(offset),
    )


def _f1(value: object) -> float | None:
    if not isinstance(value, dict):
        return None
    score = value.get("f1")
    return float(score) if isinstance(score, (int, float)) else None


def _mean(values: list[float | None]) -> float | None:
    measured = [value for value in values if value is not None]
    return round(sum(measured) / len(measured), 4) if measured else None


def _counts(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _aggregate_per_drum(metrics: list[object]) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for drum in DRUMS:
        values = [metric.get("per_drum", {}).get(drum, {}) for metric in metrics if isinstance(metric, dict)]
        tp = sum(int(value.get("tp") or 0) for value in values if isinstance(value, dict))
        fp = sum(int(value.get("fp") or 0) for value in values if isinstance(value, dict))
        fn = sum(int(value.get("fn") or 0) for value in values if isinstance(value, dict))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        result[drum] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "mean_timing_error_ticks": _mean([value.get("mean_timing_error_ticks") for value in values if isinstance(value, dict)]),
        }
    return result
