from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    job_columns = {column["name"] for column in inspect(engine).get_columns("transcription_jobs")}
    assert {
        "pipeline_mode",
        "adtof_threshold_preset",
        "tom_filter_preset",
        "runtime_fallback_status",
        "source_job_id",
    }.issubset(job_columns)
    job_indexes = {index["name"] for index in inspect(engine).get_indexes("transcription_jobs")}
    assert "ix_transcription_jobs_source_job_id" in job_indexes
    job_foreign_keys = inspect(engine).get_foreign_keys("transcription_jobs")
    assert not any("source_job_id" in foreign_key.get("constrained_columns", []) for foreign_key in job_foreign_keys)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO audio_files (
                    id,
                    original_filename,
                    content_type,
                    file_size_bytes,
                    original_storage_key
                )
                VALUES (
                    'audio-interrupted',
                    'demo.wav',
                    'audio/wav',
                    8,
                    'jobs/job-interrupted/original/demo.wav'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO transcription_jobs (
                    id,
                    audio_file_id,
                    status,
                    stage,
                    progress
                )
                VALUES (
                    'job-interrupted',
                    'audio-interrupted',
                    'interrupted',
                    'failed',
                    50
                )
                """
            )
        )
        status = connection.execute(
            text("SELECT status FROM transcription_jobs WHERE id = 'job-interrupted'")
        ).scalar_one()
        assert status == "interrupted"

    command.downgrade(config, "base")

    remaining_tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in remaining_tables
    assert not {"users", "audio_files", "transcription_jobs", "drum_tracks", "export_files"} & remaining_tables
    get_settings.cache_clear()
