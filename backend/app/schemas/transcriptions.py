from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class PipelineConfigSummary(BaseModel):
    mode: str = "unknown"
    adtof_threshold_preset: str | None = None
    tom_filter_preset: str | None = None
    runtime_fallback_status: str | None = None
    source_job_id: str | None = None


class TranscriptionJobSummary(BaseModel):
    job_id: str
    source_job_id: str | None = None
    title: str | None = None
    file_name: str
    status: str
    stage: str
    progress: int
    created_at: datetime
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    exports: dict[str, str] = Field(default_factory=dict)
    pipeline_config: PipelineConfigSummary = Field(default_factory=PipelineConfigSummary)
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


class PipelineCandidateGate(BaseModel):
    status: str = "unknown"
    run_completed: bool | None = None
    processed_event_count: int | None = None
    min_event_count: int | None = None
    kick_present: bool | None = None
    snare_present: bool | None = None
    hihat_present: bool | None = None
    blocking_flags: list[str] = Field(default_factory=list)
    musicxml_available: bool = False
    musicxml_parseable: bool = False


class PipelineQualityVerdict(BaseModel):
    verdict: str = "unknown"
    usability_score: int | None = None
    limitations: list[str] = Field(default_factory=list)
    candidate_gate: PipelineCandidateGate = Field(default_factory=PipelineCandidateGate)
    musicxml_available: bool = False
    musicxml_parseable: bool = False


class PipelineQualitySummary(BaseModel):
    raw_event_count: int | None = None
    processed_event_count: int | None = None
    raw_note_histogram: dict[str, int] = Field(default_factory=dict)
    processed_drum_counts: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float | None = None
    tempo_bpm: float | None = None
    tempo_source: str | None = None
    estimated_measure_count: int | None = None
    musicxml_parseable: bool | None = None
    visual_qa_status: str | None = None
    visual_qa_reason_code: str | None = None
    notation_readability: dict = Field(default_factory=dict)
    notation_chart: dict = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    postprocess_filters: dict[str, dict] = Field(default_factory=dict)
    quality_verdict: PipelineQualityVerdict = Field(default_factory=PipelineQualityVerdict)
    performance_gate: dict = Field(default_factory=dict)


class PipelineArtifactValidation(BaseModel):
    available: bool
    parseable: bool | None = None
    optional: bool | None = None
    openable: bool | None = None
    error_code: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PipelineVisualQaSummary(BaseModel):
    status: str
    reason_code: str | None = None
    pdf_available: bool = False
    first_page_png_available: bool = False


class PipelineValidationSummary(BaseModel):
    musicxml: PipelineArtifactValidation
    pdf: PipelineArtifactValidation
    visual_qa: PipelineVisualQaSummary | None = None


class ReviewAudioSource(BaseModel):
    kind: str
    label: str
    available: bool
    playback_url: str | None = None


class ReviewTimelineMeasure(BaseModel):
    measure_index: int
    start_seconds: float | None = None
    end_seconds: float | None = None
    render_kind: str
    drum_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PerformancePlaybackEvent(BaseModel):
    time_seconds: float
    drum: str
    velocity: int


class PerformancePlaybackSummary(BaseModel):
    available: bool = False
    event_count: int = 0
    events: list[PerformancePlaybackEvent] = Field(default_factory=list)


class ReviewTimelineSummary(BaseModel):
    schema_version: str = "1.0"
    timing_source: str = "unavailable"
    tempo_bpm: float | None = None
    audio_sources: list[ReviewAudioSource] = Field(default_factory=list)
    measures: list[ReviewTimelineMeasure] = Field(default_factory=list)
    performance_playback: PerformancePlaybackSummary | None = None


class CandidateExportResult(BaseModel):
    type: Literal["midi", "musicxml", "pdf"]
    status: str
    download_url: str | None = None


class CandidateConfigSummary(BaseModel):
    threshold: float | None = None
    adtof_threshold_preset: str | None = None
    strategy: str | None = None
    tom_filter_preset: str | None = None


class CandidateRecommendationSummary(BaseModel):
    score: int | None = None
    recommendation: Literal["recommended_for_practice", "reference_with_caveats", "reanalyze_recommended"]
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False


class CandidatePreviewResult(BaseModel):
    musicxml_url: str | None = None


class PipelineCandidateResult(BaseModel):
    candidate_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    rank: int | None = None
    position: int | None = None
    status: str
    selected: bool = False
    config: CandidateConfigSummary = Field(default_factory=CandidateConfigSummary)
    recommendation: CandidateRecommendationSummary
    preview: CandidatePreviewResult = Field(default_factory=CandidatePreviewResult)
    exports: list[CandidateExportResult] = Field(default_factory=list)
    quality: PipelineQualitySummary | None = None
    validation: PipelineValidationSummary | None = None
    review_timeline: ReviewTimelineSummary = Field(default_factory=ReviewTimelineSummary)


class PipelineCandidateAnalysis(BaseModel):
    schema_version: str = "1.0"
    status: str = "unknown"
    recommended_candidate_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    canonical_candidate_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    strategy_profile: dict = Field(default_factory=dict)
    candidates: list[PipelineCandidateResult] = Field(default_factory=list)


class PipelineSummaryResult(BaseModel):
    mode: str
    status: str | None = None
    stages: list[PipelineStageSummary] = Field(default_factory=list)
    artifacts: list[PipelineArtifactSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    config: PipelineConfigSummary = Field(default_factory=PipelineConfigSummary)
    quality: PipelineQualitySummary | None = None
    validation: PipelineValidationSummary | None = None
    pipeline_log_available: bool = False
    candidate_analysis: PipelineCandidateAnalysis | None = None


class TranscriptionResultResponse(BaseModel):
    job_id: str
    source_job_id: str | None = None
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
    review_timeline: ReviewTimelineSummary = Field(default_factory=ReviewTimelineSummary)
    source_result_summary: dict | None = None


class ReviewPacketResponse(BaseModel):
    schema_version: str
    status: str
    job: dict
    audio: dict
    exports: list[dict]
    pipeline_config: dict | None = None
    quality: dict | None = None
    validation: dict | None = None
    review_checklist: list[dict] = Field(default_factory=list)
    manual_eval_seed: dict = Field(default_factory=dict)
    audio_review: dict = Field(default_factory=dict)
    redaction: dict
