from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class InternalStageReportResponse(BaseModel):
    name: str | None = None
    status: str | None = None
    runtime_seconds: float | None = None
    artifacts: dict[str, str]
    report: dict[str, Any]
    warnings: list[Any]
    error: dict[str, Any] | None = None


class InternalPipelineErrorResponse(BaseModel):
    code: str | None = None
    message: str | None = None
    stage: str | None = None


class InternalPipelineSnapshotResponse(BaseModel):
    job_id: str
    status: str
    failed_stage: str | None = None
    artifacts: dict[str, str]
    stage_reports: list[InternalStageReportResponse]
    warnings: list[Any]
    completed_with_warning: bool
    error: InternalPipelineErrorResponse | None = None
    mock_ai: bool | None = None
    pipeline_mode: str
    pipeline_log_found: bool
