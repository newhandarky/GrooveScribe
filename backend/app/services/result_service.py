from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus
from app.services.job_query_service import JobQueryService


class ResultService:
    def __init__(self, *, settings: Settings, job_query_service: JobQueryService | None = None) -> None:
        self.settings = settings
        self.job_query_service = job_query_service or JobQueryService()

    def get_completed_result(self, db: Session, job_id: str) -> TranscriptionJob:
        job = (
            db.query(TranscriptionJob)
            .options(
                selectinload(TranscriptionJob.audio_file),
                selectinload(TranscriptionJob.drum_track),
                selectinload(TranscriptionJob.export_files),
            )
            .filter(TranscriptionJob.id == job_id)
            .one_or_none()
        )
        if job is None:
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})
        if job.status != JobStatus.COMPLETED:
            raise ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": job_id, "status": job.status.value})
        return job

    def preview_musicxml_url(self, job: TranscriptionJob) -> str | None:
        export_file = next(
            (
                export
                for export in job.export_files
                if export.type == ExportFileType.MUSICXML and export.status == ExportFileStatus.AVAILABLE
            ),
            None,
        )
        if export_file is None:
            return None
        return self.download_url(job.id, ExportFileType.MUSICXML.value)

    def download_url(self, job_id: str, export_type: str) -> str:
        return f"{self.settings.api_v1_prefix}/transcriptions/{job_id}/download/{export_type}"
