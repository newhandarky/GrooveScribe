from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MidiMetadata:
    event_count: int
    format: str = "midi"


@dataclass(frozen=True)
class DrumTranscriptionReport:
    transcriber: str
    model_name: str
    device: str
    threshold: float
    runtime_seconds: float
    command: tuple[str, ...]
    class_thresholds: dict[str, float] | None = None
    checkpoint_path: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranscriptionResult:
    raw_midi_path: Path
    metadata: MidiMetadata
    report: DrumTranscriptionReport


class DrumTranscriber(Protocol):
    def transcribe(self, drums_path: Path, output_dir: Path) -> TranscriptionResult:
        ...
