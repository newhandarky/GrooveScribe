from __future__ import annotations

from ..celery_app import celery_app


@celery_app.task(name="worker.health.ping")
def ping() -> str:
    return "pong"
