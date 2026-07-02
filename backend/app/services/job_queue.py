from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode
from app.queue import CeleryJobQueue
from app.services.local_job_queue import LocalJobQueue


class JobQueue(Protocol):
    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class NoopJobQueue:
    should_fail: bool = False

    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        if self.should_fail:
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED)


def build_job_queue(settings: Settings) -> JobQueue:
    queue_backend = settings.normalized_job_queue_backend
    if queue_backend == "local":
        return LocalJobQueue(settings=settings)
    if queue_backend == "celery":
        return CeleryJobQueue(settings=settings)
    if queue_backend == "noop":
        return NoopJobQueue()
    raise ValueError(f"unsupported job queue backend: {settings.job_queue_backend}")


def get_job_queue(settings: Settings | None = None) -> JobQueue:
    return build_job_queue(settings or get_settings())
