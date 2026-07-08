from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawMidiNoteEvent:
    tick: int
    note: int
    velocity: int
    channel: int


@dataclass(frozen=True)
class ProcessedDrumEvent:
    tick: int
    note: int
    drum: str
    velocity: int


@dataclass(frozen=True)
class MidiData:
    ticks_per_beat: int
    notes: tuple[RawMidiNoteEvent, ...]
    tempo_bpm: float | None = None
    time_signature: str = "4/4"


@dataclass(frozen=True)
class MidiPostProcessConfig:
    quantize_grid: str = "1/16"
    grid_subdivisions_per_beat: int = 4
    dedupe_window_ticks: int = 30
    velocity_floor: int = 1
    default_duration_ticks: int = 120
    tom_filter_enabled: bool = False
    tom_filter_preset: str | None = None
    tom_filter_target_max_ratio: float = 0.30
    tom_filter_core_overlap_window_ticks: int = 60


@dataclass(frozen=True)
class MidiPostProcessReport:
    input_event_count: int
    output_event_count: int
    dropped_event_count: int
    quantize_grid: str
    estimated_bpm: float
    time_signature: str
    warnings: tuple[str, ...] = ()
    raw_note_histogram: dict[int, int] | None = None
    processed_drum_counts: dict[str, int] | None = None
    postprocess_filters: dict[str, dict] | None = None


@dataclass(frozen=True)
class MidiPostProcessResult:
    processed_midi_path: Path
    drum_events_path: Path
    events: tuple[ProcessedDrumEvent, ...]
    report: MidiPostProcessReport
