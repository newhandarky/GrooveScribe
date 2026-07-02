from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GrooveScribe API"
    app_env: str = "local"
    log_level: str = "info"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+pysqlite:///./storage/local/groovescribe.db"
    job_queue_backend: str = "local"
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

    @property
    def normalized_job_queue_backend(self) -> str:
        return self.job_queue_backend.lower().strip()

    def ensure_local_app_data(self) -> None:
        Path(self.storage_root).expanduser().resolve().mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            path_part = self._sqlite_path_part()
            if path_part and path_part != ":memory:":
                Path(path_part).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def _sqlite_path_part(self) -> str | None:
        if ":///" not in self.database_url:
            return None
        return self.database_url.split(":///", maxsplit=1)[1]


@lru_cache
def get_settings() -> Settings:
    return Settings()
