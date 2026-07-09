from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiErrorException, ErrorCode, get_error_definition
from app.models import TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.models.mixins import new_uuid
from app.services.job_queue import JobQueue
from app.services.pipeline_config import normalize_pipeline_config
from app.storage.base import StorageAdapter

RETRYABLE_STATUSES = {JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.COMPLETED}
ACTIVE_STATUSES = {JobStatus.UPLOADED, JobStatus.QUEUED, JobStatus.PROCESSING}


@dataclass(frozen=True)
class RetryJobResult:
    job_id: str
    status: JobStatus
    created_at: datetime


class JobHistoryService:
    def __init__(self, *, storage: StorageAdapter, queue: JobQueue) -> None:
        self.storage = storage
        self.queue = queue

    def list_recent_jobs(self, db: Session, *, limit: int = 20) -> list[TranscriptionJob]:
        bounded_limit = max(1, min(limit, 100))
        return list(
            db.scalars(
                select(TranscriptionJob)
                .options(
                    selectinload(TranscriptionJob.audio_file),
                    selectinload(TranscriptionJob.export_files),
                )
                .order_by(desc(TranscriptionJob.created_at), desc(TranscriptionJob.id))
                .limit(bounded_limit)
            )
        )

    def retry_job(
        self,
        db: Session,
        *,
        job_id: str,
        pipeline_mode: str | None = None,
        adtof_threshold_preset: str | None = None,
        tom_filter_preset: str | None = None,
    ) -> RetryJobResult:
        source_job = db.scalar(
            select(TranscriptionJob)
            .options(selectinload(TranscriptionJob.audio_file))
            .where(TranscriptionJob.id == job_id)
        )
        if source_job is None:
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})
        if source_job.status in ACTIVE_STATUSES or source_job.status not in RETRYABLE_STATUSES:
            raise ApiErrorException(
                ErrorCode.INVALID_JOB_STATE_TRANSITION,
                details={"job_id": job_id, "status": source_job.status.value},
            )
        if not self.storage.exists(source_job.audio_file.original_storage_key):
            raise ApiErrorException(ErrorCode.ARTIFACT_NOT_FOUND, details={"job_id": job_id, "artifact": "original_audio"})

        explicit_mode = _clean(pipeline_mode) is not None
        pipeline_config = normalize_pipeline_config(
            pipeline_mode=_retry_pipeline_mode(pipeline_mode, source_job),
            adtof_threshold_preset=adtof_threshold_preset
            if explicit_mode
            else adtof_threshold_preset or source_job.adtof_threshold_preset,
            tom_filter_preset=tom_filter_preset if explicit_mode else tom_filter_preset or source_job.tom_filter_preset,
            source_job_id=source_job.id,
        )
        created_at = datetime.now(UTC)
        retry_job = TranscriptionJob(
            id=new_uuid(),
            audio_file_id=source_job.audio_file_id,
            status=JobStatus.QUEUED,
            stage=PipelineStage.QUEUED,
            progress=0,
            title=source_job.title,
            pipeline_mode=pipeline_config.pipeline_mode,
            adtof_threshold_preset=pipeline_config.adtof_threshold_preset,
            tom_filter_preset=pipeline_config.tom_filter_preset,
            runtime_fallback_status=pipeline_config.runtime_fallback_status,
            source_job_id=source_job.id,
            queued_at=created_at,
            created_at=created_at,
        )
        db.add(retry_job)
        db.commit()

        try:
            self.queue.enqueue_transcription(retry_job.id)
        except ApiErrorException as exc:
            self._mark_failed(db, retry_job.id, exc.code, PipelineStage.QUEUED.value)
            raise
        except Exception as exc:
            self._mark_failed(db, retry_job.id, ErrorCode.QUEUE_ENQUEUE_FAILED, PipelineStage.QUEUED.value)
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED) from exc

        return RetryJobResult(job_id=retry_job.id, status=JobStatus.QUEUED, created_at=created_at)

    def _mark_failed(self, db: Session, job_id: str, error_code: str | ErrorCode, error_stage: str) -> None:
        definition = get_error_definition(error_code)
        job = db.get(TranscriptionJob, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.stage = PipelineStage.FAILED
        job.error_code = definition.code
        job.error_message = definition.message
        job.error_stage = error_stage
        job.failed_at = datetime.now(UTC)
        db.commit()


def _retry_pipeline_mode(pipeline_mode: str | None, source_job: TranscriptionJob) -> str | None:
    requested_mode = _clean(pipeline_mode)
    if requested_mode is not None:
        return requested_mode
    source_mode = _clean(source_job.pipeline_mode)
    return source_mode if source_mode != "unknown" else None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
