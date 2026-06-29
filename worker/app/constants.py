from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class PipelineStage(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    SOURCE_SEPARATION = "source_separation"
    STEM_VALIDATION = "stem_validation"
    DRUM_TRANSCRIPTION = "drum_transcription"
    MIDI_POST_PROCESSING = "midi_post_processing"
    NOTATION_GENERATION = "notation_generation"
    PDF_EXPORT = "pdf_export"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportFileType(StrEnum):
    MIDI = "midi"
    MUSICXML = "musicxml"
    PDF = "pdf"


class ExportFileStatus(StrEnum):
    AVAILABLE = "available"


class ConfidenceLabel(StrEnum):
    MEDIUM = "medium"


class WorkerErrorCode(StrEnum):
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    DRUM_TRANSCRIPTION_FAILED = "DRUM_TRANSCRIPTION_FAILED"
    INVALID_JOB_STATE_TRANSITION = "INVALID_JOB_STATE_TRANSITION"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    MIDI_POST_PROCESSING_FAILED = "MIDI_POST_PROCESSING_FAILED"
    NOTATION_GENERATION_FAILED = "NOTATION_GENERATION_FAILED"
    PDF_EXPORT_FAILED = "PDF_EXPORT_FAILED"
    PIPELINE_FAILED = "PIPELINE_FAILED"
    SOURCE_SEPARATION_FAILED = "SOURCE_SEPARATION_FAILED"
    STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
    WORKER_TIMEOUT = "WORKER_TIMEOUT"
