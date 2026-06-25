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


class AudioFileResult(BaseModel):
    id: str
    original_filename: str
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


class TranscriptionResultResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    title: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    audio_file: AudioFileResult
    drum_track: DrumTrackResult | None = None
    preview: PreviewResult
    exports: list[ExportFileResult]
