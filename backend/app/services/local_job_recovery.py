from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import Callable
from datetime import UTC, datetime
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import ErrorCode, get_error_definition
from app.db.session import SessionLocal
from app.models import TranscriptionJob
from app.models.enums import JobStatus, PipelineStage

SessionFactory = Callable[[], Session]

_logger = logging.getLogger("groovescribe.local_job_recovery")


class LocalJobRecoveryService:
    def __init__(self, *, session_factory: sessionmaker[Session] | SessionFactory | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    def recover_interrupted_jobs(self) -> int:
        definition = get_error_definition(ErrorCode.PIPELINE_FAILED)
        recovered = 0
        with self.session_factory() as db:
            jobs = (
                db.query(TranscriptionJob)
                .filter(TranscriptionJob.status == JobStatus.PROCESSING)
                .all()
            )
            now = datetime.now(UTC)
            for job in jobs:
                interrupted_stage = job.stage.value if job.stage else PipelineStage.FAILED.value
                job.status = JobStatus.INTERRUPTED
                job.stage = PipelineStage.FAILED
                job.error_code = definition.code
                job.error_message = "分析流程中斷，請重新上傳或重新執行任務。"
                job.error_stage = interrupted_stage
                job.completed_at = None
                job.failed_at = now
                recovered += 1
            db.commit()
        return recovered


def build_local_job_recovery_lifespan(settings: Settings) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.normalized_job_queue_backend == "local":
            _recover_local_processing_jobs()
        yield

    return lifespan


def _recover_local_processing_jobs() -> None:
    try:
        recovered = LocalJobRecoveryService().recover_interrupted_jobs()
    except SQLAlchemyError as exc:
        _logger.warning("local job recovery skipped: %s", exc.__class__.__name__)
        return
    if recovered:
        _logger.info("local job recovery marked %s processing job(s) as interrupted", recovered)
