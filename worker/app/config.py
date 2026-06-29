from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class WorkerSettings(BaseSettings):
    app_env: str = "local"
    database_url: str = "postgresql+psycopg://groovescribe:groovescribe@localhost:5432/groovescribe"
    redis_url: str = DEFAULT_REDIS_URL
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_default_queue: str = "groovescribe"
    worker_concurrency: int = 1
    celery_task_time_limit_seconds: int = 60 * 60
    celery_task_soft_time_limit_seconds: int = 55 * 60
    storage_root: str = "./storage/local"
    pipeline_version: str = "local-poc"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend_url(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
