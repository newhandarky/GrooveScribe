from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from ..celery_app import celery_app
from ..constants import PipelineStage
from ..db import get_session_factory
from ..error_handling import map_exception_to_worker_error
from ..logging import log_event
from ..pipeline_runner import MockPipelineRunner
from ..services.job_status_service import JobNotFoundError, JobStatusService
from ..storage import LocalWorkerStorage, job_artifact_key

RunnerFactory = Callable[[], MockPipelineRunner]


@celery_app.task(name="worker.transcription.transcribe_audio")
def transcribe_audio(job_id: str, pipeline_config_id: str | None = None) -> dict[str, str]:
    return run_transcription_job(job_id, pipeline_config_id=pipeline_config_id)


def run_transcription_job(
    job_id: str,
    *,
    pipeline_config_id: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
    runner_factory: RunnerFactory | None = None,
) -> dict[str, str]:
    factory = session_factory or get_session_factory()
    runner_factory = runner_factory or MockPipelineRunner
    with factory() as session:
        runner = runner_factory()
        try:
            result = runner.run(session=session, job_id=job_id, pipeline_config_id=pipeline_config_id)
            session.commit()
            log_event(job_id=job_id, event="job_completed", stage=PipelineStage.COMPLETED.value)
            return {"job_id": job_id, "status": "completed", "log_storage_key": result.log_storage_key}
        except JobNotFoundError:
            session.rollback()
            log_event(job_id=job_id, event="job_not_found")
            return {"job_id": job_id, "status": "not_found"}
        except Exception as exc:
            current_stage = _current_stage(session, job_id)
            session.rollback()
            internal_error_ref = _write_error_log(job_id, exc, storage=runner.storage)
            try:
                error = map_exception_to_worker_error(exc, current_stage=current_stage)
                JobStatusService(session).mark_failed(
                    job_id,
                    error_code=error.code,
                    error_message=error.message,
                    error_stage=error.stage,
                    internal_error_ref=internal_error_ref,
                )
                session.commit()
                log_event(
                    job_id=job_id,
                    event="job_failed",
                    stage=error.stage,
                    error_code=error.code,
                    internal_error_ref=internal_error_ref,
                )
                return {"job_id": job_id, "status": "failed", "error_code": error.code}
            except JobNotFoundError:
                session.rollback()
                log_event(job_id=job_id, event="job_not_found_after_error")
                return {"job_id": job_id, "status": "not_found"}


def _current_stage(session: Session, job_id: str) -> str | None:
    try:
        return JobStatusService(session).get_state(job_id).stage
    except JobNotFoundError:
        return None


def _write_error_log(job_id: str, exc: Exception, *, storage: LocalWorkerStorage) -> str:
    key = job_artifact_key(job_id, "logs/pipeline.json")
    if storage.exists(key):
        return key
    storage.put_bytes(
        key,
        f'{{"job_id": "{job_id}", "event": "job_failed", "error_type": "{type(exc).__name__}"}}\n'.encode(
            "utf-8"
        ),
        "application/json",
    )
    return key
