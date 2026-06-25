from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiErrorException, ErrorCode
from app.models import ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus
from app.storage.base import StorageAdapter

_FILENAME_BY_EXPORT_TYPE: dict[ExportFileType, str] = {
    ExportFileType.MIDI: "processed_drum.mid",
    ExportFileType.MUSICXML: "score.musicxml",
    ExportFileType.PDF: "score.pdf",
}


@dataclass(frozen=True)
class DownloadArtifact:
    reader: BinaryIO
    content_type: str
    filename: str


class DownloadService:
    def __init__(self, *, storage: StorageAdapter) -> None:
        self.storage = storage

    def open_export(self, db: Session, *, job_id: str, export_type: str) -> DownloadArtifact:
        normalized_type = self._parse_export_type(export_type)
        job = (
            db.query(TranscriptionJob)
            .options(selectinload(TranscriptionJob.export_files))
            .filter(TranscriptionJob.id == job_id)
            .one_or_none()
        )
        if job is None:
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})
        if job.status != JobStatus.COMPLETED:
            raise ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": job_id, "status": job.status.value})

        export_file = self._find_export(job.export_files, normalized_type)
        if export_file is None:
            raise ApiErrorException(
                ErrorCode.EXPORT_NOT_FOUND,
                details={"job_id": job_id, "type": normalized_type.value},
            )
        if export_file.status != ExportFileStatus.AVAILABLE:
            raise ApiErrorException(
                ErrorCode.EXPORT_NOT_READY,
                details={"job_id": job_id, "type": normalized_type.value, "status": export_file.status.value},
            )

        reader = self.storage.open_reader(export_file.storage_key)
        return DownloadArtifact(
            reader=reader,
            content_type=export_file.content_type,
            filename=_FILENAME_BY_EXPORT_TYPE[normalized_type],
        )

    def _parse_export_type(self, export_type: str) -> ExportFileType:
        try:
            return ExportFileType(export_type)
        except ValueError as exc:
            raise ApiErrorException(ErrorCode.EXPORT_NOT_FOUND, details={"type": export_type}) from exc

    def _find_export(
        self,
        export_files: list[ExportFile],
        export_type: ExportFileType,
    ) -> ExportFile | None:
        return next((export for export in export_files if export.type == export_type), None)
