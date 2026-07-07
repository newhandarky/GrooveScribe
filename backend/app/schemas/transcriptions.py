from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UploadAcceptedResponse(BaseModel):
    job_id: str
    status: str = Field(examples=["queued"])
    status_url: str
    result_url: str
    created_at: datetime


class JobErrorResponse(BaseModel):
    code: str | None = None
    message: str | None = None
    stage: str | None = None
    retriable: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    progress: int
    message: str
    error: JobErrorResponse | None = None
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None


class TranscriptionJobSummary(BaseModel):
    job_id: str
    title: str | None = None
    file_name: str
    status: str
    stage: str
    progress: int
    created_at: datetime
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    exports: dict[str, str] = Field(default_factory=dict)
    error: JobErrorResponse | None = None


class TranscriptionJobListResponse(BaseModel):
    jobs: list[TranscriptionJobSummary]
    limit: int


class AudioResult(BaseModel):
    id: str
    file_name: str
    content_type: str
    file_size_bytes: int
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


class DrumTrackResult(BaseModel):
    id: str
    estimated_bpm: float | None = None
    time_signature: str
    event_count: int
    confidence_label: str | None = None
    warnings: list[str]


class ExportFileResult(BaseModel):
    type: str
    status: str
    content_type: str
    file_size_bytes: int | None = None
    checksum: str | None = None
    download_url: str | None = None


class PreviewResult(BaseModel):
    musicxml_url: str | None = None


class PipelineStageSummary(BaseModel):
    name: str
    status: str
    runtime_seconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class PipelineArtifactSummary(BaseModel):
    type: str
    available: bool
    file_size_bytes: int | None = None
    status: str | None = None


class PipelineQualitySummary(BaseModel):
    raw_event_count: int | None = None
    processed_event_count: int | None = None
    raw_note_histogram: dict[str, int] = Field(default_factory=dict)
    processed_drum_counts: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float | None = None
    tempo_bpm: float | None = None
    estimated_measure_count: int | None = None
    quality_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PipelineArtifactValidation(BaseModel):
    available: bool
    parseable: bool | None = None
    optional: bool | None = None
    openable: bool | None = None
    error_code: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PipelineValidationSummary(BaseModel):
    musicxml: PipelineArtifactValidation
    pdf: PipelineArtifactValidation


class PipelineSummaryResult(BaseModel):
    mode: str
    status: str | None = None
    stages: list[PipelineStageSummary] = Field(default_factory=list)
    artifacts: list[PipelineArtifactSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality: PipelineQualitySummary | None = None
    validation: PipelineValidationSummary | None = None
    pipeline_log_available: bool = False


class TranscriptionResultResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    title: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    audio: AudioResult
    drum_track: DrumTrackResult | None = None
    preview: PreviewResult
    exports: list[ExportFileResult]
    pipeline: PipelineSummaryResult | None = None


class ReviewPacketResponse(BaseModel):
    schema_version: str
    status: str
    job: dict
    audio: dict
    exports: list[dict]
    quality: dict | None = None
    validation: dict | None = None
    review_checklist: list[dict] = Field(default_factory=list)
    manual_eval_seed: dict = Field(default_factory=dict)
    redaction: dict
