from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from typing import Callable, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode, get_error_definition
from app.db.session import SessionLocal
from app.models import TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.services.local_pipeline_runner import LocalPipelineRunResult, LocalPipelineRunnerError
from app.services.pipeline_service import PipelineServiceRunner

SessionFactory = Callable[[], Session]


class LocalJobRunner(Protocol):
    def run(
        self,
        db: Session,
        *,
        job_id: str,
        pipeline_config_id: str | None = None,
    ) -> LocalPipelineRunResult:
        raise NotImplementedError


RunnerFactory = Callable[[], LocalJobRunner]

_DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="groovescribe-local-job")
_logger = logging.getLogger("groovescribe.local_job_queue")


class LocalJobQueue:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | SessionFactory | None = None,
        runner_factory: RunnerFactory | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal
        self.runner_factory = runner_factory or (lambda: PipelineServiceRunner(settings=self.settings))
        self.executor = executor or _DEFAULT_EXECUTOR
        self._futures: list[Future[object]] = []
        self._lock = Lock()

    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        try:
            future = self.executor.submit(self._run_job, job_id, pipeline_config_id)
        except ApiErrorException:
            raise
        except Exception as exc:
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED) from exc
        with self._lock:
            self._futures.append(future)
        future.add_done_callback(self._forget_future)

    def wait_for_all(self, *, timeout: float | None = None) -> None:
        with self._lock:
            futures = list(self._futures)
        for future in futures:
            future.result(timeout=timeout)

    def _run_job(self, job_id: str, pipeline_config_id: str | None) -> None:
        with self.session_factory() as db:
            try:
                self.runner_factory().run(db, job_id=job_id, pipeline_config_id=pipeline_config_id)
                db.commit()
            except Exception as exc:
                db.rollback()
                self._mark_failed(db, job_id, exc)
                db.commit()
                _logger.warning(
                    "local job failed: job_id=%s error_code=%s error_stage=%s",
                    job_id,
                    getattr(exc, "error_code", ErrorCode.PIPELINE_FAILED),
                    getattr(exc, "error_stage", PipelineStage.FAILED.value),
                )

    def _forget_future(self, future: Future[object]) -> None:
        with self._lock:
            if future in self._futures:
                self._futures.remove(future)

    def _mark_failed(self, db: Session, job_id: str, exc: Exception) -> None:
        job = db.get(TranscriptionJob, job_id)
        if job is None:
            return
        error_code = getattr(exc, "error_code", ErrorCode.PIPELINE_FAILED)
        error_stage = getattr(exc, "error_stage", job.stage.value if job.stage else PipelineStage.FAILED.value)
        definition = get_error_definition(error_code)
        job.status = JobStatus.FAILED
        job.stage = PipelineStage.FAILED
        job.error_code = definition.code
        job.error_message = definition.message
        job.error_stage = error_stage
        job.internal_error_ref = getattr(exc, "internal_error_ref", job.internal_error_ref)
        job.failed_at = datetime.now(UTC)


__all__ = ["LocalJobQueue", "LocalPipelineRunnerError"]
