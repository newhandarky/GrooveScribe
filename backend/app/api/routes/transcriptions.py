from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.session import get_db_session
from app.schemas.transcriptions import UploadAcceptedResponse
from app.services.job_queue import JobQueue, get_job_queue
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


async def _read_upload_file(file: UploadFile, *, max_size_bytes: int) -> bytes:
    content = await file.read(max_size_bytes + 1)
    if len(content) > max_size_bytes:
        raise ApiErrorException(
            ErrorCode.FILE_TOO_LARGE,
            details={"max_size_bytes": max_size_bytes},
        )
    return content
