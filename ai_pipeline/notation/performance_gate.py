from __future__ import annotations

import json
import statistics
import wave
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from ai_pipeline.midi.simple_midi import parse_midi
from ai_pipeline.midi.mapping import map_to_general_midi_drum


_CORE_DRUMS = {"kick", "snare", "closed_hat", "open_hat"}
_BLOCKING_CHART_WARNINGS = {
    "notation_chart_still_dense",
    "notation_fragmented_groove_rhythm",
    "chart_hihat_evidence_insufficient",
}


def evaluate_performance_score(
    *,
    chart_events_path: Path,
    performance_midi_path: Path,
    performance_musicxml_path: Path,
    drums_stem_path: Path | None,
    gate_calibration: dict | None = None,
) -> dict[str, object]:
    """Return a conservative, automation-only delivery decision.

    This validates the *rendered chart*, not the complete transcription MIDI.
    A low-confidence or unavailable audio comparison can never produce
    ``performance_ready``.
    """

    chart = _read_chart(chart_events_path)
    summary = chart.get("chart_summary") if isinstance(chart, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    events = [item for item in chart.get("events", []) if isinstance(item, dict)] if isinstance(chart, dict) else []
    ticks_per_beat = _positive_int(chart.get("ticks_per_beat"), 480)
    tempo_bpm = _positive_float(chart.get("tempo_bpm"), 120.0)
    beats = _beats(chart.get("time_signature"))
    measure_ticks = ticks_per_beat * beats

    midi_validation = _validate_midi(performance_midi_path)
    musicxml_validation, rhythm = _validate_musicxml_rhythm(performance_musicxml_path, ticks_per_beat, beats)
    playability = _validate_playability(events, summary, measure_ticks)
    alignment = _onset_alignment(events, ticks_per_beat, tempo_bpm, drums_stem_path, measure_ticks)

    issues: list[str] = []
    if not midi_validation["parseable"]:
        issues.append("performance_midi_unparseable")
    if not musicxml_validation["parseable"]:
        issues.append("performance_musicxml_unparseable")
    if not rhythm["complete"]:
        issues.append("measure_duration_incomplete")
    if rhythm["fragmented_groove_measure_count"]:
        issues.append("notation_fragmented_groove_rhythm")
    if not playability["core_groove_stable"]:
        issues.append("core_groove_unstable")
    if not playability["core_drums_present"]:
        issues.append("core_drum_missing")
    if playability["hand_conflict_measure_count"]:
        issues.append("unplayable_hand_conflict")
    if playability["tom_outside_fill_measure_count"]:
        issues.append("tom_outside_fill")
    if summary.get("dense_measures_after", 0):
        issues.append("notation_chart_still_dense")
    warnings = {str(item) for item in summary.get("warnings", [])}
    if warnings & _BLOCKING_CHART_WARNINGS:
        issues.extend(sorted(warnings & _BLOCKING_CHART_WARNINGS))

    alignment_status = str(alignment["status"])
    if alignment_status == "measured" and float(alignment["onset_alignment_rate"]) < 0.70:
        issues.append("audio_onset_alignment_low")
    elif alignment_status != "measured":
        issues.append("audio_onset_alignment_unavailable")

    issues = sorted(set(issues))
    hard_failures = {
        "performance_midi_unparseable",
        "performance_musicxml_unparseable",
        "measure_duration_incomplete",
        "notation_fragmented_groove_rhythm",
        "core_drum_missing",
        "unplayable_hand_conflict",
        "tom_outside_fill",
        "notation_chart_still_dense",
    }
    if not issues:
        verdict = "performance_ready"
    elif not (set(issues) & hard_failures) and playability["core_groove_stable"]:
        verdict = "playable_but_low_confidence"
    else:
        verdict = "not_ready"

    result = {
        "schema_version": "1.0",
        "verdict": verdict,
        "delivery_allowed": verdict == "performance_ready",
        "blocking_issues": issues,
        "midi": midi_validation,
        "musicxml": musicxml_validation,
        "rhythm": rhythm,
        "playability": playability,
        "audio_alignment": alignment,
        "ground_truth_verified": False,
        "uncalibrated_verdict": verdict,
    }
    from ai_pipeline.notation.gate_calibration import apply_gate_calibration

    return apply_gate_calibration(result, gate_calibration)


def compare_performance_midi_to_ground_truth(
    performance_midi_path: Path,
    ground_truth_midi_path: Path,
    *,
    tick_tolerance: int = 60,
) -> dict[str, object]:
    """Compare drum onsets only when an authorized chart/MIDI reference exists."""

    try:
        predicted = parse_midi(performance_midi_path)
        expected = parse_midi(ground_truth_midi_path)
    except Exception:
        return {"status": "invalid_reference", "precision": None, "recall": None, "f1": None}
    predicted_events = _mapped_onsets(predicted.notes, predicted.ticks_per_beat)
    expected_events = _mapped_onsets(expected.notes, expected.ticks_per_beat)
    matched_expected: set[int] = set()
    true_positive = 0
    matched_by_drum: dict[str, int] = defaultdict(int)
    predicted_by_drum: dict[str, int] = defaultdict(int)
    expected_by_drum: dict[str, int] = defaultdict(int)
    timing_errors: list[int] = []
    for drum, _tick in predicted_events:
        predicted_by_drum[drum] += 1
    for drum, _tick in expected_events:
        expected_by_drum[drum] += 1
    for drum, tick in predicted_events:
        candidate = next(
            (
                index
                for index, (expected_drum, expected_tick) in enumerate(expected_events)
                if index not in matched_expected and expected_drum == drum and abs(expected_tick - tick) <= tick_tolerance
            ),
            None,
        )
        if candidate is not None:
            matched_expected.add(candidate)
            true_positive += 1
            matched_by_drum[drum] += 1
            timing_errors.append(abs(expected_events[candidate][1] - tick))
    precision = true_positive / len(predicted_events) if predicted_events else 0.0
    recall = true_positive / len(expected_events) if expected_events else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    per_drum = {}
    for drum in ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal"):
        matched = matched_by_drum[drum]
        drum_precision = matched / predicted_by_drum[drum] if predicted_by_drum[drum] else 0.0
        drum_recall = matched / expected_by_drum[drum] if expected_by_drum[drum] else 0.0
        per_drum[drum] = {
            "precision": round(drum_precision, 3),
            "recall": round(drum_recall, 3),
            "f1": round(2 * drum_precision * drum_recall / (drum_precision + drum_recall), 3) if drum_precision + drum_recall else 0.0,
            "predicted_count": predicted_by_drum[drum],
            "ground_truth_count": expected_by_drum[drum],
        }
    return {
        "status": "measured",
        "predicted_onset_count": len(predicted_events),
        "ground_truth_onset_count": len(expected_events),
        "matched_onset_count": true_positive,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "tick_tolerance": tick_tolerance,
        "timing_unit": "normalized_ticks_480_tpq",
        "predicted_ticks_per_beat": predicted.ticks_per_beat,
        "ground_truth_ticks_per_beat": expected.ticks_per_beat,
        "mean_timing_error_ticks": round(sum(timing_errors) / len(timing_errors), 3) if timing_errors else None,
        "per_drum": per_drum,
    }


def _read_chart(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapped_onsets(notes: object, ticks_per_beat: int) -> list[tuple[str, float]]:
    scale = 480.0 / max(1, ticks_per_beat)
    result: list[tuple[str, float]] = []
    for note in notes if isinstance(notes, tuple | list) else []:
        mapping = map_to_general_midi_drum(note.note)
        if mapping is not None:
            result.append((mapping.drum, note.tick * scale))
    return sorted(result, key=lambda item: (item[1], item[0]))


def _validate_midi(path: Path) -> dict[str, object]:
    try:
        parsed = parse_midi(path)
    except Exception:
        return {"available": path.exists(), "parseable": False, "playback_ready": False, "event_count": 0}
    return {
        "available": True,
        "parseable": True,
        # A parsed format-0 GM channel-10 MIDI is the built-in playback contract.
        "playback_ready": bool(parsed.notes),
        "event_count": len(parsed.notes),
    }


def _validate_musicxml_rhythm(path: Path, ticks_per_beat: int, beats: int) -> tuple[dict[str, object], dict[str, object]]:
    if not path.exists():
        return {"available": False, "parseable": False}, {"complete": False, "fragmented_groove_measure_count": 0, "incomplete_voice_measure_count": 0}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {"available": True, "parseable": False}, {"complete": False, "fragmented_groove_measure_count": 0, "incomplete_voice_measure_count": 0}

    expected = ticks_per_beat * beats
    incomplete = 0
    fragmented = 0
    for measure in root.findall("./part/measure"):
        duration_by_voice: dict[str, int] = defaultdict(int)
        for note in measure.findall("note"):
            if note.find("chord") is not None:
                continue
            voice = note.findtext("voice") or "1"
            try:
                duration_by_voice[voice] += int(note.findtext("duration") or "0")
            except ValueError:
                pass
        if any(duration != expected for duration in duration_by_voice.values()):
            incomplete += 1
        if any(note.find("rest") is not None and note.findtext("type") == "16th" for note in measure.findall("note")):
            fragmented += 1
    return {"available": True, "parseable": root.tag == "score-partwise"}, {
        "complete": incomplete == 0,
        "incomplete_voice_measure_count": incomplete,
        "fragmented_groove_measure_count": fragmented,
    }


def _validate_playability(events: list[dict], summary: dict, measure_ticks: int) -> dict[str, object]:
    by_measure: dict[int, list[dict]] = defaultdict(list)
    for event in events:
        tick = event.get("tick")
        drum = event.get("drum")
        if isinstance(tick, int) and isinstance(drum, str):
            by_measure[tick // measure_ticks].append(event)
    chart_measures = {
        int(item["measure_index"]): str(item.get("render_kind", "groove"))
        for item in summary.get("chart_measures", [])
        if isinstance(item, dict) and isinstance(item.get("measure_index"), int)
    }
    core_complete = 0
    core_evidence = 0
    hand_conflicts = 0
    tom_outside_fill = 0
    for index, measure_events in by_measure.items():
        drums = {str(item.get("drum")) for item in measure_events}
        if drums & _CORE_DRUMS:
            core_evidence += 1
        if {"kick", "snare"}.issubset(drums) and drums & {"closed_hat", "open_hat"}:
            core_complete += 1
        if "tom" in drums and chart_measures.get(index, "groove") != "fill":
            tom_outside_fill += 1
        by_tick: dict[int, set[str]] = defaultdict(set)
        for event in measure_events:
            by_tick[int(event["tick"])].add(str(event["drum"]))
        if any({"closed_hat", "open_hat"} & items and "cymbal" in items for items in by_tick.values()):
            hand_conflicts += 1
    ratio = core_complete / core_evidence if core_evidence else 0.0
    return {
        "core_drums_present": core_complete > 0,
        "core_groove_measure_count": core_complete,
        "core_groove_ratio": round(ratio, 3),
        "core_groove_stable": core_complete >= 2 and ratio >= 0.65,
        "hand_conflict_measure_count": hand_conflicts,
        "tom_outside_fill_measure_count": tom_outside_fill,
    }


def _onset_alignment(events: list[dict], ticks_per_beat: int, tempo_bpm: float, drums_stem_path: Path | None, measure_ticks: int) -> dict[str, object]:
    if drums_stem_path is None or not drums_stem_path.exists():
        return {"status": "unavailable", "onset_alignment_rate": None, "measured_event_count": 0, "measure_confidence": {}}
    onsets = _wav_onsets(drums_stem_path)
    if not onsets:
        return {"status": "unavailable", "onset_alignment_rate": None, "measured_event_count": 0, "measure_confidence": {}}
    seconds_per_tick = 60.0 / (tempo_bpm * ticks_per_beat)
    per_measure: dict[int, list[bool]] = defaultdict(list)
    for event in events:
        if event.get("drum") not in _CORE_DRUMS or not isinstance(event.get("tick"), int):
            continue
        timestamp = int(event["tick"]) * seconds_per_tick
        aligned = any(abs(timestamp - onset) <= 0.09 for onset in onsets)
        per_measure[int(event["tick"]) // measure_ticks].append(aligned)
    measured = sum(len(values) for values in per_measure.values())
    if not measured:
        return {"status": "unavailable", "onset_alignment_rate": None, "measured_event_count": 0, "measure_confidence": {}}
    measure_confidence = {str(index + 1): round(sum(values) / len(values), 3) for index, values in sorted(per_measure.items())}
    rate = sum(sum(values) for values in per_measure.values()) / measured
    return {"status": "measured", "onset_alignment_rate": round(rate, 3), "measured_event_count": measured, "measure_confidence": measure_confidence}


def _wav_onsets(path: Path) -> list[float]:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getsampwidth() not in {2, 4}:
                return []
            rate, width = source.getframerate(), source.getsampwidth()
            window = max(1, rate // 50)
            values: list[float] = []
            while frames := source.readframes(window):
                if width == 2:
                    samples = memoryview(frames).cast("h")
                    scale = 32768.0
                else:
                    samples = memoryview(frames).cast("i")
                    scale = 2147483648.0
                values.append(sum(abs(sample) for sample in samples) / max(1, len(samples)) / scale)
    except (OSError, wave.Error):
        return []
    if len(values) < 3:
        return []
    baseline = statistics.median(values)
    threshold = max(baseline * 1.8, 0.008)
    return [index / 50.0 for index in range(1, len(values) - 1) if values[index] >= threshold and values[index] >= values[index - 1] and values[index] > values[index + 1]]


def _positive_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default


def _positive_float(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and value > 0 else default


def _beats(value: object) -> int:
    try:
        result = int(str(value or "4/4").split("/", 1)[0])
    except ValueError:
        return 4
    return result if result > 0 else 4
