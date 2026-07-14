from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


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
    ai_python_path: str = Field(
        default=str(_REPO_ROOT / ".venv-ai" / "bin" / "python"),
        validation_alias=AliasChoices("AI_PYTHON", "AI_PYTHON_PATH"),
    )
    pipeline_mock_ai: bool = True
    pipeline_export_pdf: bool = True
    pipeline_require_pdf: bool = False
    pipeline_timeout_seconds: int = 3600
    pipeline_demucs_model_name: str = "htdemucs"
    pipeline_demucs_device: str = Field(
        default="auto",
        validation_alias=AliasChoices("PIPELINE_DEMUCS_DEVICE", "GROOVESCRIBE_DEMUCS_DEVICE"),
    )
    pipeline_demucs_timeout_seconds: int = 1800
    pipeline_adtof_command_template: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PIPELINE_ADTOF_COMMAND_TEMPLATE",
            "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE",
        ),
    )
    pipeline_adtof_checkpoint_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PIPELINE_ADTOF_CHECKPOINT", "GROOVESCRIBE_ADTOF_CHECKPOINT"),
    )
    pipeline_adtof_device: str = Field(
        default="cpu",
        validation_alias=AliasChoices("PIPELINE_ADTOF_DEVICE", "GROOVESCRIBE_ADTOF_DEVICE"),
    )
    pipeline_adtof_threshold: float = Field(
        default=0.5,
        validation_alias=AliasChoices("PIPELINE_ADTOF_THRESHOLD", "GROOVESCRIBE_ADTOF_THRESHOLD"),
    )
    pipeline_adtof_verify_input_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PIPELINE_ADTOF_VERIFY_INPUT", "GROOVESCRIBE_ADTOF_VERIFY_INPUT"),
    )
    pipeline_adtof_verify_output_dir: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PIPELINE_ADTOF_VERIFY_OUTPUT_DIR", "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"),
    )
    pipeline_adtof_timeout_seconds: int = 1800
    pipeline_performance_gate_calibration_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PIPELINE_PERFORMANCE_GATE_CALIBRATION",
            "GROOVESCRIBE_PERFORMANCE_GATE_CALIBRATION",
        ),
    )
    pipeline_pdf_renderer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PIPELINE_PDF_RENDERER", "GROOVESCRIBE_PDF_RENDERER"),
    )
    runtime_preflight_timeout_seconds: int = 30
    upload_max_size_bytes: int = 100 * 1024 * 1024
    upload_max_duration_seconds: int = 10 * 60
    upload_metadata_timeout_seconds: int = 5
    upload_title_max_length: int = 120
    internal_api_enabled: bool = False
    internal_api_token: str | None = None
    internal_api_token_label: str = "internal"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True)

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def normalized_job_queue_backend(self) -> str:
        return self.job_queue_backend.lower().strip()

    @property
    def resolved_storage_root(self) -> str:
        return str(self._resolve_local_path(self.storage_root))

    @property
    def resolved_database_url(self) -> str:
        if not self.database_url.startswith("sqlite"):
            return self.database_url
        path_part = self._sqlite_path_part()
        if path_part is None or path_part == ":memory:":
            return self.database_url
        scheme = self.database_url.split(":///", maxsplit=1)[0]
        return f"{scheme}:///{self._resolve_local_path(path_part)}"

    def ensure_local_app_data(self) -> None:
        Path(self.resolved_storage_root).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            path_part = self._sqlite_path_part()
            if path_part and path_part != ":memory:":
                self._resolve_local_path(path_part).parent.mkdir(parents=True, exist_ok=True)

    def _sqlite_path_part(self) -> str | None:
        if ":///" not in self.database_url:
            return None
        return self.database_url.split(":///", maxsplit=1)[1]

    def _resolve_local_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (_REPO_ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
