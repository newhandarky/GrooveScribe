from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GrooveScribe API"
    app_env: str = "local"
    log_level: str = "info"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://groovescribe:groovescribe@localhost:5432/groovescribe"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_default_queue: str = "groovescribe"
    storage_root: str = "./storage/local"
    upload_max_size_bytes: int = 100 * 1024 * 1024
    upload_max_duration_seconds: int = 10 * 60
    upload_metadata_timeout_seconds: int = 5
    upload_title_max_length: int = 120
    internal_api_enabled: bool = False
    internal_api_token: str | None = None
    internal_api_token_label: str = "internal"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
