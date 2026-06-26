from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def _alembic_config() -> Config:
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "backend" / "migrations"))
    return config


def test_alembic_upgrade_head_and_downgrade_base(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = _alembic_config()

    command.upgrade(config, "head")

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "users",
        "audio_files",
        "transcription_jobs",
        "drum_tracks",
        "export_files",
        "alembic_version",
    }.issubset(tables)

    command.downgrade(config, "base")

    remaining_tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in remaining_tables
    assert not {"users", "audio_files", "transcription_jobs", "drum_tracks", "export_files"} & remaining_tables
    get_settings.cache_clear()
