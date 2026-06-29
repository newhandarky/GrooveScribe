from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from app.constants import JobStatus, PipelineStage
from app.db import audio_files, metadata, transcription_jobs


def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def seed_queued_job(session: Session, *, job_id: str = "job-1") -> None:
    session.execute(
        insert(audio_files).values(
            id=f"audio-{job_id}",
            original_filename="demo.wav",
            content_type="audio/wav",
            file_size_bytes=8,
            duration_seconds=30.0,
            original_storage_key=f"jobs/{job_id}/original/demo.wav",
        )
    )
    session.execute(
        insert(transcription_jobs).values(
            id=job_id,
            audio_file_id=f"audio-{job_id}",
            status=JobStatus.QUEUED.value,
            stage=PipelineStage.QUEUED.value,
            progress=0,
            pipeline_version="local-poc",
        )
    )
    session.commit()
