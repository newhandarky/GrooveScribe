from __future__ import annotations

from celery import Celery

from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode

TRANSCRIPTION_TASK_NAME = "worker.transcription.transcribe_audio"


class CeleryJobQueue:
    def __init__(self, settings: Settings | None = None, celery_app: Celery | None = None) -> None:
        self.settings = settings or get_settings()
        self.celery_app = celery_app or Celery(
            "groovescribe_backend",
            broker=self.settings.resolved_celery_broker_url,
            backend=self.settings.resolved_celery_result_backend,
        )
        self.celery_app.conf.update(task_default_queue=self.settings.celery_task_default_queue)

    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        kwargs = {"pipeline_config_id": pipeline_config_id} if pipeline_config_id is not None else {}
        try:
            self.celery_app.send_task(
                TRANSCRIPTION_TASK_NAME,
                args=[job_id],
                kwargs=kwargs,
                queue=self.settings.celery_task_default_queue,
            )
        except ApiErrorException:
            raise
        except Exception as exc:
            raise ApiErrorException(ErrorCode.QUEUE_ENQUEUE_FAILED) from exc
