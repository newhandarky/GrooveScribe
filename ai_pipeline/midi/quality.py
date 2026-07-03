from __future__ import annotations

from collections import Counter
from math import ceil
from pathlib import Path
from typing import Iterable

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import DEFAULT_TEMPO_BPM, parse_midi
from ai_pipeline.midi.types import RawMidiNoteEvent

QUALITY_FLAG_CODES = {
    "too_few_events",
    "sparse_transcription",
    "hihat_missing_likely",
    "mostly_tom_output",
    "no_snare_detected",
}


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


def quality_flag_subset(warnings: Iterable[str]) -> list[str]:
    return sorted({warning for warning in warnings if warning in QUALITY_FLAG_CODES})


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
