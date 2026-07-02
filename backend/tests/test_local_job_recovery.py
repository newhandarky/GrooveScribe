from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.models import AudioFile, TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.services import local_job_recovery
from app.services.local_job_recovery import LocalJobRecoveryService


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_job(session, *, job_id: str, status: JobStatus, stage: PipelineStage) -> None:
    audio = AudioFile(
        id=f"audio-{job_id}",
        original_filename="demo.wav",
        content_type="audio/wav",
        file_size_bytes=8,
        original_storage_key=f"jobs/{job_id}/original/demo.wav",
    )
    session.add(
        TranscriptionJob(
            id=job_id,
            audio_file=audio,
            status=status,
            stage=stage,
            progress=45 if status == JobStatus.PROCESSING else 0,
        )
    )


def test_local_job_recovery_marks_only_processing_jobs_interrupted(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    with session_factory() as session:
        _seed_job(
            session,
            job_id="job-processing",
            status=JobStatus.PROCESSING,
            stage=PipelineStage.DRUM_TRANSCRIPTION,
        )
        _seed_job(session, job_id="job-queued", status=JobStatus.QUEUED, stage=PipelineStage.QUEUED)
        _seed_job(session, job_id="job-completed", status=JobStatus.COMPLETED, stage=PipelineStage.COMPLETED)
        session.commit()

    recovered = LocalJobRecoveryService(session_factory=session_factory).recover_interrupted_jobs()

    assert recovered == 1
    with session_factory() as session:
        jobs = {
            job.id: job
            for job in session.scalars(select(TranscriptionJob).order_by(TranscriptionJob.id)).all()
        }
        interrupted = jobs["job-processing"]
        assert interrupted.status == JobStatus.INTERRUPTED
        assert interrupted.stage == PipelineStage.FAILED
        assert interrupted.progress == 45
        assert interrupted.error_code == "PIPELINE_FAILED"
        assert interrupted.error_stage == PipelineStage.DRUM_TRANSCRIPTION.value
        assert interrupted.failed_at is not None
        assert jobs["job-queued"].status == JobStatus.QUEUED
        assert jobs["job-completed"].status == JobStatus.COMPLETED


def test_lifespan_startup_runs_local_job_recovery(tmp_path: Path, monkeypatch) -> None:
    session_factory = _session_factory(tmp_path)
    with session_factory() as session:
        _seed_job(
            session,
            job_id="job-processing",
            status=JobStatus.PROCESSING,
            stage=PipelineStage.SOURCE_SEPARATION,
        )
        session.commit()
    monkeypatch.setattr(local_job_recovery, "SessionLocal", session_factory)
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}",
        storage_root=str(tmp_path / "storage"),
        job_queue_backend="local",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-processing"))
        assert job.status == JobStatus.INTERRUPTED
        assert job.stage == PipelineStage.FAILED
        assert job.error_stage == PipelineStage.SOURCE_SEPARATION.value


def test_lifespan_startup_skips_recovery_for_non_local_queue(tmp_path: Path, monkeypatch) -> None:
    session_factory = _session_factory(tmp_path)
    with session_factory() as session:
        _seed_job(
            session,
            job_id="job-processing",
            status=JobStatus.PROCESSING,
            stage=PipelineStage.SOURCE_SEPARATION,
        )
        session.commit()
    monkeypatch.setattr(local_job_recovery, "SessionLocal", session_factory)
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}",
        storage_root=str(tmp_path / "storage"),
        job_queue_backend="celery",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-processing"))
        assert job.status == JobStatus.PROCESSING
        assert job.stage == PipelineStage.SOURCE_SEPARATION


def test_create_app_does_not_register_deprecated_startup_event(monkeypatch) -> None:
    def fail_on_event(self, event_type):
        raise AssertionError(f"deprecated on_event used: {event_type}")

    monkeypatch.setattr(FastAPI, "on_event", fail_on_event)

    app = create_app(Settings(job_queue_backend="noop"))

    assert isinstance(app, FastAPI)
