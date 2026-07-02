from pathlib import Path

from app.core.config import Settings


def test_settings_default_to_local_first_backend(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JOB_QUEUE_BACKEND", raising=False)

    settings = Settings()

    assert settings.database_url == "sqlite+pysqlite:///./storage/local/groovescribe.db"
    assert settings.normalized_job_queue_backend == "local"
    assert settings.storage_root == "./storage/local"


def test_settings_env_override_preserves_server_mode_options(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/groovescribe")
    monkeypatch.setenv("JOB_QUEUE_BACKEND", "celery")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost:5432/groovescribe"
    assert settings.normalized_job_queue_backend == "celery"


def test_ensure_local_app_data_creates_storage_and_sqlite_parent(tmp_path: Path) -> None:
    db_path = tmp_path / "storage" / "local" / "groovescribe.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        storage_root=str(tmp_path / "storage" / "local"),
    )

    settings.ensure_local_app_data()

    assert Path(settings.storage_root).exists()
    assert db_path.parent.exists()
