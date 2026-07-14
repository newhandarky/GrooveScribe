from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArtifactType(StrEnum):
    ORIGINAL_AUDIO = "original_audio"
    NORMALIZED_AUDIO = "normalized_audio"
    DRUMS_STEM = "drums_stem"
    RAW_MIDI = "raw_midi"
    PROCESSED_MIDI = "processed_midi"
    PERFORMANCE_MIDI = "performance_midi"
    DRUM_EVENTS = "drum_events"
    CHART_EVENTS = "chart_events"
    VISUAL_PREVIEW = "visual_preview"
    MUSICXML = "musicxml"
    PDF = "pdf"
    PIPELINE_LOG = "pipeline_log"


CONTENT_TYPE_BY_ARTIFACT_TYPE: dict[ArtifactType, str] = {
    ArtifactType.ORIGINAL_AUDIO: "application/octet-stream",
    ArtifactType.NORMALIZED_AUDIO: "audio/wav",
    ArtifactType.DRUMS_STEM: "audio/wav",
    ArtifactType.RAW_MIDI: "audio/midi",
    ArtifactType.PROCESSED_MIDI: "audio/midi",
    ArtifactType.PERFORMANCE_MIDI: "audio/midi",
    ArtifactType.DRUM_EVENTS: "application/json",
    ArtifactType.CHART_EVENTS: "application/json",
    ArtifactType.VISUAL_PREVIEW: "image/png",
    ArtifactType.MUSICXML: "application/vnd.recordare.musicxml+xml",
    ArtifactType.PDF: "application/pdf",
    ArtifactType.PIPELINE_LOG: "application/json",
}


@dataclass(frozen=True)
class ArtifactRef:
    storage_key: str
    content_type: str
    file_size_bytes: int | None = None
    checksum: str | None = None
    artifact_type: ArtifactType | None = None


@dataclass(frozen=True)
class DownloadUrl:
    url: str
    expires_in_seconds: int | None = None
