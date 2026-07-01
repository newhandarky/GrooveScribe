from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotationConfig:
    title: str = "GrooveScribe Drum Draft"
    composer: str = "GrooveScribe"
    part_name: str = "Drums"
    divisions_per_quarter: int | None = None
    note_duration_ticks: int | None = None


@dataclass(frozen=True)
class MusicXmlResult:
    musicxml_path: Path
    event_count: int
    measure_count: int
    title: str


@dataclass(frozen=True)
class PdfExportResult:
    pdf_path: Path
    renderer: str
    warnings: tuple[str, ...] = ()
