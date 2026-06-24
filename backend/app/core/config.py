from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    log_level: str = "info"
    database_url: str = "postgresql+psycopg://groovescribe:groovescribe@localhost:5432/groovescribe"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: str = "./storage/local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
