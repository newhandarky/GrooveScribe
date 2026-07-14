from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi

DRUMS = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_TOLERANCE_TICKS = 60


def compare_drum_midi(predicted_path: Path, ground_truth_path: Path) -> dict[str, Any]:
    """Compare mapped drum onsets on a shared 480-PPQ timing grid."""
    try:
        predicted = _mapped_onsets(predicted_path)
        expected = _mapped_onsets(ground_truth_path)
    except Exception:
        return {"status": "unavailable", "per_drum": {}, "f1": None, "mean_timing_error_ticks": None}

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
        "per_drum": per_drum,
        "f1": round(macro_f1, 4),
        "scored_drum_classes": scored_drums,
        "excluded_empty_drum_classes": [drum for drum in DRUMS if drum not in scored_drums],
        "mean_timing_error_ticks": round(sum(all_errors) / len(all_errors), 3) if all_errors else None,
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


def _mapped_onsets(path: Path) -> dict[str, list[float]]:
    parsed = parse_midi(path)
    scale = 480.0 / max(1, parsed.ticks_per_beat)
    result: dict[str, list[float]] = defaultdict(list)
    for note in parsed.notes:
        mapping = map_to_general_midi_drum(note.note)
        if mapping is not None and mapping.drum in DRUMS:
            result[mapping.drum].append(note.tick * scale)
    return {drum: sorted(result[drum]) for drum in DRUMS}


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
