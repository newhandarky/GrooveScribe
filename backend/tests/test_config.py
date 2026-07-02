from pathlib import Path

from app.core.config import Settings


def test_settings_default_to_local_first_backend(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JOB_QUEUE_BACKEND", raising=False)
    monkeypatch.delenv("AI_PYTHON", raising=False)
    monkeypatch.delenv("AI_PYTHON_PATH", raising=False)

    settings = Settings()

    assert settings.database_url == "sqlite+pysqlite:///./storage/local/groovescribe.db"
    assert settings.normalized_job_queue_backend == "local"
    assert settings.storage_root == "./storage/local"
    assert settings.ai_python_path.endswith(".venv-ai/bin/python")
    assert settings.pipeline_mock_ai is True
    assert settings.pipeline_export_pdf is True
    assert settings.pipeline_require_pdf is False
    assert settings.pipeline_timeout_seconds == 3600
    assert settings.pipeline_demucs_model_name == "htdemucs"
    assert settings.pipeline_demucs_device == "auto"
    assert settings.pipeline_adtof_command_template is None
    assert settings.pipeline_adtof_device == "cpu"
    assert settings.pipeline_adtof_threshold == 0.5


def test_settings_env_override_preserves_server_mode_options(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/groovescribe")
    monkeypatch.setenv("JOB_QUEUE_BACKEND", "celery")
    monkeypatch.setenv("AI_PYTHON", "/opt/groovescribe-ai/bin/python")
    monkeypatch.setenv("GROOVESCRIBE_DEMUCS_DEVICE", "cpu")
    monkeypatch.setenv(
        "GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE",
        "/opt/groovescribe-ai/bin/adtof --audio {input} --out {output}",
    )

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost:5432/groovescribe"
    assert settings.normalized_job_queue_backend == "celery"
    assert settings.ai_python_path == "/opt/groovescribe-ai/bin/python"
    assert settings.pipeline_demucs_device == "cpu"
    assert settings.pipeline_adtof_command_template == "/opt/groovescribe-ai/bin/adtof --audio {input} --out {output}"


def test_ensure_local_app_data_creates_storage_and_sqlite_parent(tmp_path: Path) -> None:
    db_path = tmp_path / "storage" / "local" / "groovescribe.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        storage_root=str(tmp_path / "storage" / "local"),
    )

    settings.ensure_local_app_data()

    assert Path(settings.storage_root).exists()
    assert db_path.parent.exists()
