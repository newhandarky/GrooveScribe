from __future__ import annotations

from celery import Celery

from .config import WorkerSettings, get_worker_settings


def _task_modules() -> tuple[str, ...]:
    package = __package__ or "app"
    return (f"{package}.tasks.health", f"{package}.tasks.transcription")


def create_celery_app(settings: WorkerSettings | None = None) -> Celery:
    worker_settings = settings or get_worker_settings()
    app = Celery(
        "groovescribe_worker",
        broker=worker_settings.broker_url,
        backend=worker_settings.result_backend_url,
        include=_task_modules(),
    )
    app.conf.update(
        accept_content=["json"],
        result_serializer="json",
        task_default_queue=worker_settings.celery_task_default_queue,
        task_serializer="json",
        task_soft_time_limit=worker_settings.celery_task_soft_time_limit_seconds,
        task_time_limit=worker_settings.celery_task_time_limit_seconds,
        task_track_started=True,
        timezone="UTC",
        worker_concurrency=worker_settings.worker_concurrency,
    )
    return app


celery_app = create_celery_app()
