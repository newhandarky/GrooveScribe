from __future__ import annotations

from app.celery_app import celery_app, create_celery_app
from app.config import WorkerSettings, get_worker_settings
from app.tasks.health import ping


def test_celery_app_can_be_created() -> None:
    app = create_celery_app(WorkerSettings())

    assert app.main == "groovescribe_worker"
    assert app.conf.task_default_queue == "groovescribe"
    assert app.conf.worker_concurrency == 1
    assert app.conf.task_time_limit == 3600
    assert app.conf.task_soft_time_limit == 3300


def test_broker_and_backend_can_be_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/1")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker:6379/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://backend:6379/3")
    get_worker_settings.cache_clear()

    settings = get_worker_settings()
    app = create_celery_app(settings)

    assert settings.redis_url == "redis://redis:6379/1"
    assert app.conf.broker_url == "redis://broker:6379/2"
    assert app.conf.result_backend == "redis://backend:6379/3"

    get_worker_settings.cache_clear()


def test_broker_and_backend_fall_back_to_redis_url() -> None:
    app = create_celery_app(WorkerSettings(redis_url="redis://localhost:6380/5"))

    assert app.conf.broker_url == "redis://localhost:6380/5"
    assert app.conf.result_backend == "redis://localhost:6380/5"


def test_ping_task_is_registered() -> None:
    assert "worker.health.ping" in celery_app.tasks
    assert ping.name == "worker.health.ping"
    assert ping.run() == "pong"
