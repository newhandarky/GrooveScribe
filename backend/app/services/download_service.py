from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiErrorException, ErrorCode
from app.models import ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus
from app.storage.base import StorageAdapter
from app.storage.errors import ArtifactNotFoundError
from app.storage.keys import sanitize_filename

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

        try:
            reader = self.storage.open_reader(export_file.storage_key)
        except ArtifactNotFoundError as exc:
            raise ApiErrorException(
                ErrorCode.EXPORT_NOT_FOUND,
                details={"job_id": job_id, "type": normalized_type.value},
            ) from exc
        return DownloadArtifact(
            reader=reader,
            content_type=export_file.content_type,
            filename=_download_filename(export_file),
        )

    def open_review_audio(self, db: Session, *, job_id: str, audio_kind: str) -> DownloadArtifact:
        job = (
            db.query(TranscriptionJob)
            .options(selectinload(TranscriptionJob.audio_file), selectinload(TranscriptionJob.drum_track))
            .filter(TranscriptionJob.id == job_id)
            .one_or_none()
        )
        if job is None:
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})
        if job.status != JobStatus.COMPLETED:
            raise ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": job_id, "status": job.status.value})
        if audio_kind == "original":
            storage_key = job.audio_file.original_storage_key
            content_type = job.audio_file.content_type
            filename = sanitize_filename(job.audio_file.original_filename)
        elif audio_kind == "drums_stem" and job.drum_track and job.drum_track.drums_stem_storage_key:
            storage_key = job.drum_track.drums_stem_storage_key
            content_type = "audio/wav"
            filename = "drums_stem.wav"
        else:
            raise ApiErrorException(ErrorCode.EXPORT_NOT_FOUND, details={"job_id": job_id, "type": audio_kind})
        try:
            reader = self.storage.open_reader(storage_key)
        except ArtifactNotFoundError as exc:
            raise ApiErrorException(ErrorCode.EXPORT_NOT_FOUND, details={"job_id": job_id, "type": audio_kind}) from exc
        return DownloadArtifact(reader=reader, content_type=content_type, filename=filename)

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


def _download_filename(export_file: ExportFile) -> str:
    stored_name = export_file.storage_key.rsplit("/", maxsplit=1)[-1]
    if export_file.type == ExportFileType.MIDI and stored_name == "performance_score.mid":
        return stored_name
    if export_file.type == ExportFileType.MUSICXML and stored_name == "performance_score.musicxml":
        return stored_name
    return _FILENAME_BY_EXPORT_TYPE[export_file.type]
