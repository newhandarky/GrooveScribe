from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.session import get_db_session
from app.models import TranscriptionJob
from app.models.enums import ExportFileStatus
from app.schemas.transcriptions import (
    AudioResult,
    DrumTrackResult,
    ExportFileResult,
    JobErrorResponse,
    JobStatusResponse,
    PreviewResult,
    ReviewPacketResponse,
    TranscriptionJobListResponse,
    TranscriptionJobSummary,
    TranscriptionResultResponse,
    UploadAcceptedResponse,
)
from app.services.download_service import DownloadService
from app.services.job_history_service import JobHistoryService, RetryJobResult
from app.services.job_query_service import JobQueryService
from app.services.job_queue import JobQueue, get_job_queue
from app.services.result_service import ResultService
from app.services.review_packet_service import ReviewPacketService
from app.services.upload_service import UploadService
from app.storage.base import StorageAdapter
from app.storage.dependencies import get_storage_adapter

router = APIRouter(prefix="/transcriptions", tags=["transcriptions"])


def get_upload_service(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> UploadService:
    return UploadService(settings=settings, storage=storage, queue=queue)


def get_job_query_service() -> JobQueryService:
    return JobQueryService()


def get_result_service(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
    job_query_service: Annotated[JobQueryService, Depends(get_job_query_service)],
) -> ResultService:
    return ResultService(settings=settings, storage=storage, job_query_service=job_query_service)


def get_job_history_service(
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobHistoryService:
    return JobHistoryService(storage=storage, queue=queue)


def get_download_service(
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> DownloadService:
    return DownloadService(storage=storage)


def get_review_packet_service(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> ReviewPacketService:
    return ReviewPacketService(settings=settings, storage=storage)


@router.get("", response_model=TranscriptionJobListResponse)
def list_transcriptions(
    db: Annotated[Session, Depends(get_db_session)],
    job_history_service: Annotated[JobHistoryService, Depends(get_job_history_service)],
    job_query_service: Annotated[JobQueryService, Depends(get_job_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TranscriptionJobListResponse:
    jobs = job_history_service.list_recent_jobs(db, limit=limit)
    return TranscriptionJobListResponse(
        jobs=[_build_job_summary(job, job_query_service) for job in jobs],
        limit=limit,
    )


@router.post("", response_model=UploadAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_transcription(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_service: Annotated[UploadService, Depends(get_upload_service)],
    title: Annotated[str | None, Form()] = None,
) -> UploadAcceptedResponse:
    content = await _read_upload_file(file, max_size_bytes=settings.upload_max_size_bytes)
    result = upload_service.create_upload_job(
        db=db,
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
        title=title,
    )
    base_path = f"{settings.api_v1_prefix}/transcriptions/{result.job_id}"
    return UploadAcceptedResponse(
        job_id=result.job_id,
        status=result.status.value,
        status_url=f"{base_path}/status",
        result_url=base_path,
        created_at=result.created_at,
    )


@router.post("/{job_id}/retry", response_model=UploadAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_transcription(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    job_history_service: Annotated[JobHistoryService, Depends(get_job_history_service)],
) -> UploadAcceptedResponse:
    result = job_history_service.retry_job(db, job_id=job_id)
    return _build_upload_response(result, settings)


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_transcription_status(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    job_query_service: Annotated[JobQueryService, Depends(get_job_query_service)],
) -> JobStatusResponse:
    job = job_query_service.get_job_or_raise(db, job_id)
    error = job_query_service.error_payload(job)
    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        stage=job.stage.value,
        progress=job.progress,
        message=job_query_service.stage_message(job),
        error=JobErrorResponse(**error) if error else None,
        created_at=job.created_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        failed_at=job.failed_at,
    )


@router.get("/{job_id}", response_model=TranscriptionResultResponse)
def get_transcription_result(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    result_service: Annotated[ResultService, Depends(get_result_service)],
) -> TranscriptionResultResponse:
    job = result_service.get_completed_result(db, job_id)
    return _build_result_response(job, result_service)


@router.get("/{job_id}/review-packet", response_model=ReviewPacketResponse)
def get_transcription_review_packet(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    review_packet_service: Annotated[ReviewPacketService, Depends(get_review_packet_service)],
) -> ReviewPacketResponse:
    return ReviewPacketResponse(**review_packet_service.build_packet(db, job_id=job_id))


@router.get("/{job_id}/download/review-packet")
def download_transcription_review_packet(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    review_packet_service: Annotated[ReviewPacketService, Depends(get_review_packet_service)],
) -> Response:
    packet_zip = review_packet_service.build_zip(db, job_id=job_id)
    return Response(
        packet_zip.content,
        media_type=packet_zip.content_type,
        headers={"Content-Disposition": f'attachment; filename="{packet_zip.filename}"'},
    )


@router.get("/{job_id}/download/{export_type}")
def download_transcription_export(
    job_id: str,
    export_type: str,
    db: Annotated[Session, Depends(get_db_session)],
    download_service: Annotated[DownloadService, Depends(get_download_service)],
) -> StreamingResponse:
    artifact = download_service.open_export(db, job_id=job_id, export_type=export_type)
    headers = {"Content-Disposition": f'attachment; filename="{artifact.filename}"'}
    return StreamingResponse(
        artifact.reader,
        media_type=artifact.content_type,
        headers=headers,
        background=BackgroundTask(artifact.reader.close),
    )


async def _read_upload_file(file: UploadFile, *, max_size_bytes: int) -> bytes:
    content = await file.read(max_size_bytes + 1)
    if len(content) > max_size_bytes:
        raise ApiErrorException(
            ErrorCode.FILE_TOO_LARGE,
            details={"max_size_bytes": max_size_bytes},
        )
    return content


def _build_result_response(
    job: TranscriptionJob,
    result_service: ResultService,
) -> TranscriptionResultResponse:
    audio_file = job.audio_file
    drum_track = job.drum_track
    return TranscriptionResultResponse(
        job_id=job.id,
        status=job.status.value,
        stage=job.stage.value,
        title=job.title,
        created_at=job.created_at,
        completed_at=job.completed_at,
        audio=AudioResult(
            id=audio_file.id,
            file_name=audio_file.original_filename,
            content_type=audio_file.content_type,
            file_size_bytes=audio_file.file_size_bytes,
            duration_seconds=audio_file.duration_seconds,
            sample_rate=audio_file.sample_rate,
            channels=audio_file.channels,
        ),
        drum_track=(
            DrumTrackResult(
                id=drum_track.id,
                estimated_bpm=drum_track.estimated_bpm,
                time_signature=drum_track.time_signature,
                event_count=drum_track.event_count,
                confidence_label=drum_track.confidence_label.value if drum_track.confidence_label else None,
                warnings=drum_track.warnings,
            )
            if drum_track
            else None
        ),
        preview=PreviewResult(musicxml_url=result_service.preview_musicxml_url(job)),
        exports=[
            ExportFileResult(
                type=export.type.value,
                status=export.status.value,
                content_type=export.content_type,
                file_size_bytes=export.file_size_bytes,
                checksum=export.checksum,
                download_url=(
                    result_service.download_url(job.id, export.type.value)
                    if export.status == ExportFileStatus.AVAILABLE
                    else None
                ),
            )
            for export in sorted(job.export_files, key=lambda item: item.type.value)
        ],
        pipeline=result_service.pipeline_summary(job),
    )


def _build_upload_response(result: RetryJobResult, settings: Settings) -> UploadAcceptedResponse:
    base_path = f"{settings.api_v1_prefix}/transcriptions/{result.job_id}"
    return UploadAcceptedResponse(
        job_id=result.job_id,
        status=result.status.value,
        status_url=f"{base_path}/status",
        result_url=base_path,
        created_at=result.created_at,
    )


def _build_job_summary(
    job: TranscriptionJob,
    job_query_service: JobQueryService,
) -> TranscriptionJobSummary:
    error = job_query_service.error_payload(job)
    return TranscriptionJobSummary(
        job_id=job.id,
        title=job.title,
        file_name=job.audio_file.original_filename,
        status=job.status.value,
        stage=job.stage.value,
        progress=job.progress,
        created_at=job.created_at,
        completed_at=job.completed_at,
        failed_at=job.failed_at,
        exports={export.type.value: export.status.value for export in sorted(job.export_files, key=lambda item: item.type.value)},
        error=JobErrorResponse(**error) if error else None,
    )
