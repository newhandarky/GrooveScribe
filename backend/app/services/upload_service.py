from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode, get_error_definition
from app.models import AudioFile, TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.models.mixins import new_uuid
from app.services.audio_metadata import (
    AudioMetadata,
    AudioMetadataInspectionError,
    AudioMetadataInspector,
)
from app.services.job_queue import JobQueue
from app.storage import ArtifactType, StorageAdapter, build_job_artifact_key, sanitize_filename

_ALLOWED_EXTENSIONS = {".mp3", ".wav"}
_ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
}


@dataclass(frozen=True)
class UploadResult:
    job_id: str
    status: JobStatus
    created_at: datetime


class UploadService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageAdapter,
        queue: JobQueue,
        metadata_inspector: AudioMetadataInspector | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.queue = queue
        self.metadata_inspector = metadata_inspector or AudioMetadataInspector()

    def create_upload_job(
        self,
        *,
        db: Session,
        filename: str,
        content_type: str | None,
        content: bytes,
        title: str | None = None,
    ) -> UploadResult:
        safe_filename = self._validate_file(filename=filename, content_type=content_type, content=content)
        clean_title = self._validate_title(title)
        metadata = self._inspect_metadata(
            content=content,
            filename=safe_filename,
            content_type=content_type or "",
        )

        audio_file_id = new_uuid()
        job_id = new_uuid()
        original_storage_key = build_job_artifact_key(
            job_id,
            ArtifactType.ORIGINAL_AUDIO,
            filename=safe_filename,
        )

        created_at = datetime.now(UTC)
        audio_file = AudioFile(
            id=audio_file_id,
            original_filename=safe_filename,
            content_type=content_type or "application/octet-stream",
            file_size_bytes=len(content),
            duration_seconds=metadata.duration_seconds,
            sample_rate=metadata.sample_rate,
            channels=metadata.channels,
            original_storage_key=original_storage_key,
        )
        job = TranscriptionJob(
            id=job_id,
            audio_file_id=audio_file_id,
            status=JobStatus.UPLOADED,
            stage=PipelineStage.UPLOADED,
            progress=0,
            title=clean_title,
        )

        db.add(audio_file)
        db.add(job)
        db.commit()

        try:
            self.storage.put_bytes(content, original_storage_key, content_type or "application/octet-stream")
        except Exception as exc:
            self._mark_job_failed(
                db,
                job_id,
                error_code=getattr(exc, "code", ErrorCode.STORAGE_WRITE_FAILED),
                error_stage=PipelineStage.UPLOADED.value,
            )
            raise

        job.status = JobStatus.QUEUED
        job.stage = PipelineStage.QUEUED
        job.queued_at = created_at
        db.commit()

        try:
            self.queue.enqueue_transcription(job_id)
        except ApiErrorException as exc:
            self._mark_job_failed(db, job_id, error_code=exc.code, error_stage=PipelineStage.QUEUED.value)
            raise
        except Exception as exc:
            self._mark_job_failed(
                db,
                job_id,
                error_code=ErrorCode.QUEUE_ENQUEUE_FAILED,
                error_stage=PipelineStage.QUEUED.value,
            )
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED) from exc

        return UploadResult(job_id=job_id, status=JobStatus.QUEUED, created_at=created_at)

    def _mark_job_failed(
        self,
        db: Session,
        job_id: str,
        *,
        error_code: str | ErrorCode,
        error_stage: str,
    ) -> None:
        definition = get_error_definition(error_code)
        try:
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
        except Exception:
            db.rollback()
            raise

    def _validate_file(self, *, filename: str, content_type: str | None, content: bytes) -> str:
        if not filename:
            raise ApiErrorException(ErrorCode.INVALID_FILE_TYPE)

        safe_filename = sanitize_filename(filename)
        extension = Path(safe_filename).suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise ApiErrorException(ErrorCode.INVALID_FILE_TYPE)

        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise ApiErrorException(ErrorCode.INVALID_FILE_TYPE)

        if len(content) > self.settings.upload_max_size_bytes:
            raise ApiErrorException(
                ErrorCode.FILE_TOO_LARGE,
                details={"max_size_bytes": self.settings.upload_max_size_bytes},
            )

        if not content:
            raise ApiErrorException(ErrorCode.AUDIO_METADATA_UNREADABLE)

        return safe_filename

    def _validate_title(self, title: str | None) -> str | None:
        if title is None:
            return None
        clean_title = title.strip()
        if not clean_title:
            return None
        if len(clean_title) > self.settings.upload_title_max_length:
            raise ApiErrorException(
                ErrorCode.VALIDATION_ERROR,
                details={"field": "title", "max_length": self.settings.upload_title_max_length},
            )
        return clean_title

    def _inspect_metadata(self, *, content: bytes, filename: str, content_type: str) -> AudioMetadata:
        try:
            metadata = self.metadata_inspector.inspect(
                content,
                filename=filename,
                content_type=content_type,
                timeout_seconds=self.settings.upload_metadata_timeout_seconds,
            )
        except AudioMetadataInspectionError as exc:
            raise ApiErrorException(ErrorCode.AUDIO_METADATA_UNREADABLE) from exc

        if metadata.duration_seconds > self.settings.upload_max_duration_seconds:
            raise ApiErrorException(
                ErrorCode.AUDIO_TOO_LONG,
                details={"max_duration_seconds": self.settings.upload_max_duration_seconds},
            )
        return metadata
