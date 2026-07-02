from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode, get_error_definition
from app.db.session import SessionLocal
from app.models import TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.services.local_pipeline_runner import LocalMockPipelineRunner, LocalPipelineRunnerError

SessionFactory = Callable[[], Session]
RunnerFactory = Callable[[], LocalMockPipelineRunner]

_DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="groovescribe-local-job")


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
        self.runner_factory = runner_factory or (lambda: LocalMockPipelineRunner(settings=self.settings))
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
