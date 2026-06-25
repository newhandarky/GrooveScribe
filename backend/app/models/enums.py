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


class ConfidenceLabel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExportFileType(StrEnum):
    MIDI = "midi"
    MUSICXML = "musicxml"
    PDF = "pdf"


class ExportFileStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"
