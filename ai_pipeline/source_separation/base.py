from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StemMetadata:
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    format: str


@dataclass(frozen=True)
class SourceSeparationReport:
    separator: str
    model_name: str
    device: str
    runtime_seconds: float
    command: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StemSet:
    drums_path: Path
    metadata: StemMetadata
    report: SourceSeparationReport
    accompaniment_path: Path | None = None


class SourceSeparator(Protocol):
    def separate(self, input_path: Path, output_dir: Path) -> StemSet:
        ...
