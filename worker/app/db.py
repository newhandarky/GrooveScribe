from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_worker_settings

metadata = MetaData()

audio_files = Table(
    "audio_files",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("original_filename", String(512), nullable=False),
    Column("content_type", String(255), nullable=False),
    Column("file_size_bytes", BigInteger, nullable=False),
    Column("duration_seconds", Float),
    Column("sample_rate", Integer),
    Column("channels", Integer),
    Column("original_storage_key", String(1024), nullable=False),
    Column("normalized_storage_key", String(1024)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

transcription_jobs = Table(
    "transcription_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("audio_file_id", String(36), ForeignKey("audio_files.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("stage", String(64), nullable=False),
    Column("progress", Integer, nullable=False, default=0),
    Column("title", String(512)),
    Column("pipeline_version", String(64), nullable=False, default="poc-local-v1"),
    Column("source_separator", String(128)),
    Column("source_separator_version", String(128)),
    Column("drum_transcriber", String(128)),
    Column("drum_transcriber_version", String(128)),
    Column("error_code", String(128)),
    Column("error_message", Text),
    Column("error_stage", String(128)),
    Column("internal_error_ref", String(1024)),
    Column("queued_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("failed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

drum_tracks = Table(
    "drum_tracks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", String(36), ForeignKey("transcription_jobs.id"), nullable=False, unique=True),
    Column("drums_stem_storage_key", String(1024)),
    Column("raw_midi_storage_key", String(1024)),
    Column("processed_midi_storage_key", String(1024)),
    Column("drum_events_storage_key", String(1024)),
    Column("estimated_bpm", Float),
    Column("time_signature", String(16), nullable=False, default="4/4"),
    Column("event_count", Integer, nullable=False, default=0),
    Column("confidence_label", String(32)),
    Column("warnings", JSON, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

export_files = Table(
    "export_files",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", String(36), ForeignKey("transcription_jobs.id"), nullable=False),
    Column("type", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("storage_key", String(1024), nullable=False),
    Column("content_type", String(255), nullable=False),
    Column("file_size_bytes", BigInteger),
    Column("checksum", String(128)),
    Column("error_code", String(128)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = create_engine(database_url or get_worker_settings().database_url, pool_pre_ping=True)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session_factory() -> sessionmaker[Session]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(get_worker_settings().database_url, pool_pre_ping=True)
        _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _session_factory


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session
