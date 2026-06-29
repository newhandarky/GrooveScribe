from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.errors import ApiErrorException, ErrorCode
from app.queue import CeleryJobQueue


class JobQueue(Protocol):
    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class NoopJobQueue:
    should_fail: bool = False

    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        if self.should_fail:
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED)


def get_job_queue() -> JobQueue:
    return CeleryJobQueue()
