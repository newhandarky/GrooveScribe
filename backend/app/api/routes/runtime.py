from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.runtime import RuntimePreflightResponse
from app.services.runtime_diagnostics import RuntimeDiagnosticsService

router = APIRouter(prefix="/runtime", tags=["runtime"])


def get_runtime_diagnostics_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RuntimeDiagnosticsService:
    return RuntimeDiagnosticsService(settings=settings)


@router.get("/preflight", response_model=RuntimePreflightResponse)
def get_runtime_preflight(
    service: Annotated[RuntimeDiagnosticsService, Depends(get_runtime_diagnostics_service)],
) -> RuntimePreflightResponse:
    return service.get_preflight()
