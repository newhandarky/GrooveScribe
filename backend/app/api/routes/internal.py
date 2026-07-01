from __future__ import annotations

import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException
from app.db.session import get_db_session
from app.schemas.internal import InternalPipelineSnapshotResponse
from app.services.internal_job_detail_service import InternalJobDetailService
from app.services.internal_snapshot_redaction import redact_pipeline_snapshot
from app.storage.base import StorageAdapter
from app.storage.dependencies import get_storage_adapter

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)
_bearer = HTTPBearer(auto_error=False)
_logger = logging.getLogger("groovescribe.internal")


def get_internal_job_detail_service(
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> InternalJobDetailService:
    return InternalJobDetailService(storage=storage)


def require_internal_bearer(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    if credentials is None:
        _audit(request=request, status_code=status.HTTP_401_UNAUTHORIZED, auth_subject=None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="internal authorization required")
    if not settings.internal_api_token:
        _audit(request=request, status_code=status.HTTP_403_FORBIDDEN, auth_subject=settings.internal_api_token_label)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal api token is not configured")
    if not secrets.compare_digest(credentials.credentials, settings.internal_api_token):
        _audit(request=request, status_code=status.HTTP_403_FORBIDDEN, auth_subject=settings.internal_api_token_label)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal authorization")
    return settings.internal_api_token_label


@router.get("/jobs/{job_id}/pipeline-snapshot", response_model=InternalPipelineSnapshotResponse)
def get_internal_pipeline_snapshot(
    job_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    service: Annotated[InternalJobDetailService, Depends(get_internal_job_detail_service)],
    auth_subject: Annotated[str, Depends(require_internal_bearer)],
) -> InternalPipelineSnapshotResponse:
    try:
        snapshot = service.get_pipeline_snapshot(db, job_id)
    except ApiErrorException as exc:
        _audit(request=request, job_id=job_id, status_code=exc.status_code, auth_subject=auth_subject)
        raise
    _audit(request=request, job_id=job_id, status_code=status.HTTP_200_OK, auth_subject=auth_subject)
    return InternalPipelineSnapshotResponse(**redact_pipeline_snapshot(snapshot))


def _audit(
    *,
    request: Request,
    status_code: int,
    auth_subject: str | None,
    job_id: str | None = None,
) -> None:
    payload = {
        "event": "internal_pipeline_snapshot_read",
        "job_id": job_id,
        "request_id": request.headers.get("x-request-id"),
        "client_host": request.client.host if request.client else None,
        "auth_subject": auth_subject,
        "status_code": status_code,
    }
    _logger.info(json.dumps({key: value for key, value in payload.items() if value is not None}, sort_keys=True))
