from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.local_data import LocalDataSummaryResponse
from app.services.local_data_service import LocalDataSummaryService

router = APIRouter(prefix="/local-data", tags=["local-data"])


@router.get("/summary", response_model=LocalDataSummaryResponse)
def get_local_data_summary(
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LocalDataSummaryResponse:
    return LocalDataSummaryResponse(**LocalDataSummaryService(settings=settings).summary(db))
