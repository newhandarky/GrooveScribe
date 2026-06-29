from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..constants import JobStatus, PipelineStage, WorkerErrorCode
from ..db import transcription_jobs, utc_now


class JobNotFoundError(Exception):
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"job not found: {job_id}")


class InvalidJobStateTransitionError(Exception):
    def __init__(self, job_id: str, current_status: str | None, target_status: str) -> None:
        self.job_id = job_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"invalid job state transition for {job_id}: {current_status} -> {target_status}")


@dataclass(frozen=True)
class JobState:
    id: str
    status: str
    stage: str
    progress: int


class JobStatusService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_state(self, job_id: str) -> JobState:
        row = self.session.execute(
            select(
                transcription_jobs.c.id,
                transcription_jobs.c.status,
                transcription_jobs.c.stage,
                transcription_jobs.c.progress,
            ).where(transcription_jobs.c.id == job_id)
        ).mappings().one_or_none()
        if row is None:
            raise JobNotFoundError(job_id)
        return JobState(
            id=row["id"],
            status=row["status"],
            stage=row["stage"],
            progress=row["progress"],
        )

    def mark_processing(self, job_id: str) -> None:
        state = self.get_state(job_id)
        if state.status != JobStatus.QUEUED.value:
            raise InvalidJobStateTransitionError(job_id, state.status, JobStatus.PROCESSING.value)
        now = utc_now()
        self.session.execute(
            update(transcription_jobs)
            .where(transcription_jobs.c.id == job_id)
            .values(
                status=JobStatus.PROCESSING.value,
                stage=PipelineStage.PREPROCESSING.value,
                progress=10,
                started_at=now,
                updated_at=now,
            )
        )

    def update_stage(self, job_id: str, stage: str | PipelineStage, progress: int) -> None:
        state = self.get_state(job_id)
        if state.status != JobStatus.PROCESSING.value:
            raise InvalidJobStateTransitionError(job_id, state.status, JobStatus.PROCESSING.value)
        if progress < 0 or progress > 100:
            raise ValueError("progress must be between 0 and 100")
        now = utc_now()
        self.session.execute(
            update(transcription_jobs)
            .where(transcription_jobs.c.id == job_id)
            .values(stage=str(stage), progress=progress, updated_at=now)
        )

    def mark_completed(self, job_id: str) -> None:
        state = self.get_state(job_id)
        if state.status != JobStatus.PROCESSING.value:
            raise InvalidJobStateTransitionError(job_id, state.status, JobStatus.COMPLETED.value)
        now = utc_now()
        self.session.execute(
            update(transcription_jobs)
            .where(transcription_jobs.c.id == job_id)
            .values(
                status=JobStatus.COMPLETED.value,
                stage=PipelineStage.COMPLETED.value,
                progress=100,
                completed_at=now,
                error_code=None,
                error_message=None,
                error_stage=None,
                updated_at=now,
            )
        )

    def mark_failed(
        self,
        job_id: str,
        *,
        error_code: str | WorkerErrorCode,
        error_message: str,
        error_stage: str | PipelineStage,
        internal_error_ref: str | None = None,
    ) -> None:
        state = self.get_state(job_id)
        if state.status in {JobStatus.COMPLETED.value, JobStatus.CANCELED.value}:
            raise InvalidJobStateTransitionError(job_id, state.status, JobStatus.FAILED.value)
        if not error_code or not error_message or not error_stage:
            raise ValueError("failed job requires error_code, error_message, and error_stage")
        now = utc_now()
        self.session.execute(
            update(transcription_jobs)
            .where(transcription_jobs.c.id == job_id)
            .values(
                status=JobStatus.FAILED.value,
                stage=PipelineStage.FAILED.value,
                error_code=str(error_code),
                error_message=error_message,
                error_stage=str(error_stage),
                internal_error_ref=internal_error_ref,
                failed_at=now,
                updated_at=now,
            )
        )
