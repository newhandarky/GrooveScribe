from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotationConfig:
    title: str = "GrooveScribe Drum Draft"
    composer: str = "GrooveScribe"
    part_name: str = "Drums"
    layout_profile: str = "standard_drum_v1"
    chart_mode: str = "readable_drum_chart_v3"
    max_chart_events_per_measure: int = 8
    tempo_bpm_override: float | None = None
    divisions_per_quarter: int | None = None
    note_duration_ticks: int | None = None


@dataclass(frozen=True)
class MusicXmlResult:
    musicxml_path: Path
    chart_events_path: Path
    event_count: int
    chart_event_count: int
    measure_count: int
    title: str
    readability_summary: dict
    chart_summary: dict
    tempo_bpm: float
    tempo_source: str


@dataclass(frozen=True)
class PdfExportResult:
    pdf_path: Path
    renderer: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MuseScoreVisualQaResult:
    status: str
    reason_code: str | None
    pdf_path: Path | None = None
    first_page_png_path: Path | None = None

    def report(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "pdf_available": self.pdf_path is not None,
            "first_page_png_available": self.first_page_png_path is not None,
        }
