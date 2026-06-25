from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GrooveScribe API"
    app_env: str = "local"
    log_level: str = "info"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://groovescribe:groovescribe@localhost:5432/groovescribe"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: str = "./storage/local"
    upload_max_size_bytes: int = 100 * 1024 * 1024
    upload_max_duration_seconds: int = 10 * 60
    upload_metadata_timeout_seconds: int = 5
    upload_title_max_length: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
