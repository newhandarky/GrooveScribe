from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.storage.errors import PathTraversalRejectedError
from app.storage.types import ArtifactType

_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    cleaned = _SAFE_FILENAME_PATTERN.sub("_", filename.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.replace("_.", ".")
    cleaned = cleaned.strip("._")
    if not cleaned:
        raise PathTraversalRejectedError("filename is empty after sanitization")
    if cleaned in {".", ".."}:
        raise PathTraversalRejectedError(f"unsafe filename: {filename}")
    return cleaned[:255]


def sanitize_storage_key(storage_key: str) -> str:
    if not storage_key or storage_key.strip() != storage_key:
        raise PathTraversalRejectedError("storage key is empty or has surrounding whitespace")
    if chr(92) in storage_key:
        raise PathTraversalRejectedError("backslashes are not allowed in storage keys")

    path = PurePosixPath(storage_key)
    if path.is_absolute():
        raise PathTraversalRejectedError("absolute storage keys are not allowed")

    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise PathTraversalRejectedError(f"unsafe storage key: {storage_key}")

    return str(path)


def build_job_artifact_key(
    job_id: str,
    artifact_type: ArtifactType,
    filename: str | None = None,
) -> str:
    safe_job_id = sanitize_filename(job_id)
    if artifact_type == ArtifactType.ORIGINAL_AUDIO:
        if filename is None:
            raise ValueError("original audio artifact requires filename")
        key = f"jobs/{safe_job_id}/original/{sanitize_filename(filename)}"
    elif artifact_type == ArtifactType.NORMALIZED_AUDIO:
        key = f"jobs/{safe_job_id}/audio/normalized.wav"
    elif artifact_type == ArtifactType.DRUMS_STEM:
        key = f"jobs/{safe_job_id}/stems/drums.wav"
    elif artifact_type == ArtifactType.ACCOMPANIMENT_STEM:
        key = f"jobs/{safe_job_id}/stems/no_drums.wav"
    elif artifact_type == ArtifactType.RAW_MIDI:
        key = f"jobs/{safe_job_id}/midi/raw_drum.mid"
    elif artifact_type == ArtifactType.PROCESSED_MIDI:
        key = f"jobs/{safe_job_id}/midi/processed_drum.mid"
    elif artifact_type == ArtifactType.PERFORMANCE_MIDI:
        key = f"jobs/{safe_job_id}/notation/performance_score.mid"
    elif artifact_type == ArtifactType.DRUM_EVENTS:
        key = f"jobs/{safe_job_id}/midi/drum_events.json"
    elif artifact_type == ArtifactType.CHART_EVENTS:
        key = f"jobs/{safe_job_id}/notation/chart_events.json"
    elif artifact_type == ArtifactType.VISUAL_PREVIEW:
        key = f"jobs/{safe_job_id}/notation/score_preview.png"
    elif artifact_type == ArtifactType.MUSICXML:
        key = f"jobs/{safe_job_id}/notation/score.musicxml"
    elif artifact_type == ArtifactType.PDF:
        key = f"jobs/{safe_job_id}/exports/score.pdf"
    elif artifact_type == ArtifactType.PIPELINE_LOG:
        key = f"jobs/{safe_job_id}/logs/pipeline.json"
    else:
        raise ValueError(f"unsupported artifact type: {artifact_type}")
    return sanitize_storage_key(key)


def build_candidate_artifact_key(job_id: str, candidate_id: str, artifact_type: ArtifactType) -> str:
    """Build a storage-only key for a known candidate artifact."""

    safe_job_id = sanitize_filename(job_id)
    safe_candidate_id = sanitize_filename(candidate_id)
    filenames = {
        ArtifactType.RAW_MIDI: "midi/raw_drum.mid",
        ArtifactType.PROCESSED_MIDI: "midi/processed_drum.mid",
        ArtifactType.PERFORMANCE_MIDI: "notation/performance_score.mid",
        ArtifactType.DRUM_EVENTS: "midi/drum_events.json",
        ArtifactType.CHART_EVENTS: "notation/chart_events.json",
        ArtifactType.MUSICXML: "notation/score.musicxml",
        ArtifactType.PDF: "exports/score.pdf",
    }
    relative = filenames.get(artifact_type)
    if relative is None:
        raise ValueError(f"artifact type is not a candidate artifact: {artifact_type}")
    return sanitize_storage_key(f"jobs/{safe_job_id}/candidates/{safe_candidate_id}/{relative}")
