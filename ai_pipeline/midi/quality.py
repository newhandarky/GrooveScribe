from __future__ import annotations

from collections import Counter
from math import ceil
from pathlib import Path
from typing import Iterable, Mapping

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import DEFAULT_TEMPO_BPM, parse_midi
from ai_pipeline.midi.types import RawMidiNoteEvent

BLOCKING_CANDIDATE_FLAGS = {
    "no_usable_groove",
    "sparse_transcription",
    "too_few_events",
    "mostly_tom_output",
    "no_snare_detected",
}
QUALITY_FLAG_CODES = {
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
MIN_CANDIDATE_EVENT_COUNT = 4


def inspect_midi_quality(midi_path: Path) -> dict:
    midi = parse_midi(midi_path)
    note_histogram = Counter(event.note for event in midi.notes)
    mapped_counts, unmapped_count = mapped_drum_counts(midi.notes)
    duration_seconds = _duration_seconds(
        max((event.tick for event in midi.notes), default=0),
        ticks_per_beat=midi.ticks_per_beat,
        tempo_bpm=midi.tempo_bpm or DEFAULT_TEMPO_BPM,
    )
    estimated_measure_count = _estimated_measure_count(
        duration_ticks=max((event.tick for event in midi.notes), default=0),
        ticks_per_beat=midi.ticks_per_beat,
        time_signature=midi.time_signature,
    )
    flags = quality_flags(
        event_count=len(midi.notes),
        drum_counts=mapped_counts,
        estimated_measure_count=estimated_measure_count,
    )

    return {
        "schema_version": "2.0",
        "path_name": midi_path.name,
        "event_count": len(midi.notes),
        "ticks_per_beat": midi.ticks_per_beat,
        "tempo_bpm": midi.tempo_bpm,
        "time_signature": midi.time_signature,
        "duration_seconds": duration_seconds,
        "estimated_measure_count": estimated_measure_count,
        "note_histogram": {str(key): value for key, value in sorted(note_histogram.items())},
        "mapped_drum_counts": dict(sorted(mapped_counts.items())),
        "unmapped_event_count": unmapped_count,
        "quality_flags": sorted(flags),
    }


def mapped_drum_counts(events: Iterable[RawMidiNoteEvent]) -> tuple[Counter[str], int]:
    mapped_counts: Counter[str] = Counter()
    unmapped_count = 0
    for event in events:
        mapping = map_to_general_midi_drum(event.note)
        if mapping is None:
            unmapped_count += 1
            continue
        mapped_counts[mapping.drum] += 1
    return mapped_counts, unmapped_count


def quality_flags(
    *,
    event_count: int,
    drum_counts: Counter[str],
    estimated_measure_count: int | None = None,
) -> set[str]:
    flags: set[str] = set()
    if event_count < 4:
        flags.add("too_few_events")
    if event_count and (event_count < 8 or _events_per_measure(event_count, estimated_measure_count) < 2):
        flags.add("sparse_transcription")

    hihat_count = sum(drum_counts.get(drum, 0) for drum in ("closed_hat", "pedal_hat", "open_hat"))
    if event_count >= 4 and hihat_count == 0:
        flags.add("hihat_missing_likely")
    if event_count >= 4 and drum_counts.get("snare", 0) == 0:
        flags.add("no_snare_detected")

    tom_count = drum_counts.get("tom", 0)
    if event_count >= 3 and tom_count / event_count >= 0.75:
        flags.add("mostly_tom_output")
    return flags


def quality_diagnostics(
    *,
    raw_note_histogram: Mapping[int | str, int] | None = None,
    processed_drum_counts: Mapping[str, int] | None = None,
    raw_event_count: int | None = None,
    processed_event_count: int | None = None,
    estimated_measure_count: int | None = None,
) -> set[str]:
    raw_counts = _normalize_note_histogram(raw_note_histogram or {})
    processed_counts = Counter(processed_drum_counts or {})
    processed_count = processed_event_count
    if processed_count is None:
        processed_count = sum(processed_counts.values())
    raw_count = raw_event_count
    if raw_count is None:
        raw_count = sum(raw_counts.values())

    flags = quality_flags(
        event_count=processed_count,
        drum_counts=processed_counts,
        estimated_measure_count=estimated_measure_count,
    )

    if raw_count >= 3:
        raw_tom_count = 0
        for note, count in raw_counts.items():
            mapping = map_to_general_midi_drum(note)
            if mapping is not None and mapping.drum == "tom":
                raw_tom_count += count
        if raw_tom_count / raw_count >= 0.75:
            flags.add("raw_tom_dominant")

    hihat_count = sum(processed_counts.get(drum, 0) for drum in ("closed_hat", "pedal_hat", "open_hat"))
    kick_count = processed_counts.get("kick", 0)
    snare_count = processed_counts.get("snare", 0)
    other_count = processed_count - kick_count - snare_count - hihat_count
    if processed_count >= 2 and kick_count and snare_count and hihat_count == 0 and other_count == 0:
        flags.add("kick_snare_only")
    if processed_count >= 4 and sum(1 for count in (kick_count, snare_count, hihat_count) if count > 0) < 2:
        flags.add("missing_core_groove")
    if processed_count < 4 or (kick_count == 0 and snare_count == 0):
        flags.add("no_usable_groove")
    return flags


def quality_flag_subset(warnings: Iterable[str]) -> list[str]:
    return sorted({warning for warning in warnings if warning in QUALITY_FLAG_CODES})


def evaluate_drum_draft_quality(
    *,
    processed_drum_counts: Mapping[str, int] | None = None,
    processed_event_count: int | None = None,
    quality_flags: Iterable[str] | None = None,
    musicxml_available: bool = False,
    musicxml_parseable: bool = False,
    run_completed: bool = True,
) -> dict:
    counts = Counter(processed_drum_counts or {})
    flags = {str(flag) for flag in (quality_flags or [])}
    event_count = processed_event_count
    if event_count is None:
        event_count = sum(counts.values())
    hihat_count = _hihat_count(counts)
    blocking_flags = sorted(flags & BLOCKING_CANDIDATE_FLAGS)
    candidate_passed = (
        run_completed
        and event_count >= MIN_CANDIDATE_EVENT_COUNT
        and bool(counts.get("kick"))
        and bool(counts.get("snare"))
        and hihat_count > 0
        and not blocking_flags
        and musicxml_available
        and musicxml_parseable
    )
    score = _usability_score(
        candidate_passed=candidate_passed,
        event_count=event_count,
        counts=counts,
        blocking_flags=blocking_flags,
        musicxml_available=musicxml_available,
        musicxml_parseable=musicxml_parseable,
        run_completed=run_completed,
    )
    if candidate_passed and score >= 4:
        verdict = "mvp_candidate"
    elif candidate_passed:
        verdict = "draft_candidate_needs_review"
    else:
        verdict = "not_candidate"
    return {
        "schema_version": "1.0",
        "verdict": verdict,
        "usability_score": score,
        "candidate_gate": {
            "status": "passed" if candidate_passed else "failed",
            "run_completed": run_completed,
            "processed_event_count": event_count,
            "min_event_count": MIN_CANDIDATE_EVENT_COUNT,
            "kick_present": bool(counts.get("kick")),
            "snare_present": bool(counts.get("snare")),
            "hihat_present": hihat_count > 0,
            "blocking_flags": blocking_flags,
            "musicxml_available": musicxml_available,
            "musicxml_parseable": musicxml_parseable,
        },
        "limitations": _quality_limitations(
            counts=counts,
            event_count=event_count,
            blocking_flags=blocking_flags,
            musicxml_available=musicxml_available,
            musicxml_parseable=musicxml_parseable,
        ),
    }


def _normalize_note_histogram(histogram: Mapping[int | str, int]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for note, count in histogram.items():
        try:
            note_number = int(note)
            event_count = int(count)
        except (TypeError, ValueError):
            continue
        if event_count > 0:
            counts[note_number] += event_count
    return counts


def _duration_seconds(duration_ticks: int, *, ticks_per_beat: int, tempo_bpm: float) -> float | None:
    if duration_ticks <= 0 or ticks_per_beat <= 0 or tempo_bpm <= 0:
        return None
    beats = duration_ticks / ticks_per_beat
    return round(beats * 60 / tempo_bpm, 3)


def _estimated_measure_count(
    *,
    duration_ticks: int,
    ticks_per_beat: int,
    time_signature: str,
) -> int | None:
    if duration_ticks <= 0 or ticks_per_beat <= 0:
        return None
    numerator = _time_signature_numerator(time_signature)
    beats = duration_ticks / ticks_per_beat
    return max(1, ceil(beats / numerator))


def _time_signature_numerator(time_signature: str) -> int:
    try:
        numerator_text, _ = time_signature.split("/", 1)
        numerator = int(numerator_text)
    except (AttributeError, ValueError):
        return 4
    return numerator if numerator > 0 else 4


def _events_per_measure(event_count: int, estimated_measure_count: int | None) -> float:
    if not estimated_measure_count:
        return float(event_count)
    return event_count / estimated_measure_count


def _usability_score(
    *,
    candidate_passed: bool,
    event_count: int,
    counts: Counter[str],
    blocking_flags: list[str],
    musicxml_available: bool,
    musicxml_parseable: bool,
    run_completed: bool,
) -> int:
    if not run_completed or not musicxml_available or not musicxml_parseable:
        return 1
    if not candidate_passed:
        return 1 if {"no_usable_groove", "too_few_events"} & set(blocking_flags) else 2
    snare_count = counts.get("snare", 0)
    hihat_count = _hihat_count(counts)
    tom_count = counts.get("tom", 0)
    tom_ratio = tom_count / event_count if event_count else 1.0
    if snare_count >= 3 and hihat_count >= 4 and tom_ratio <= 0.2:
        return 5
    if snare_count >= 2 and hihat_count >= 2 and tom_ratio <= 0.3:
        return 4
    return 3


def _quality_limitations(
    *,
    counts: Counter[str],
    event_count: int,
    blocking_flags: list[str],
    musicxml_available: bool,
    musicxml_parseable: bool,
) -> list[str]:
    limitations = list(blocking_flags)
    if not musicxml_available:
        limitations.append("musicxml_unavailable")
    elif not musicxml_parseable:
        limitations.append("musicxml_unparseable")
    if counts.get("kick", 0) == 0:
        limitations.append("kick_missing")
    if counts.get("snare", 0) == 0:
        limitations.append("snare_missing")
    if _hihat_count(counts) == 0:
        limitations.append("hihat_missing")
    tom_count = counts.get("tom", 0)
    if event_count and tom_count / event_count > 0.3:
        limitations.append("tom_false_positive_likely")
    return sorted(set(limitations))


def _hihat_count(counts: Mapping[str, int]) -> int:
    return sum(int(counts.get(drum, 0)) for drum in ("closed_hat", "pedal_hat", "open_hat"))
