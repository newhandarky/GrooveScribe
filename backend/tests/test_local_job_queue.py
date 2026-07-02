from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.local_job_queue import LocalJobQueue
from app.services.local_pipeline_runner import LocalMockPipelineRunner
from app.storage.local import LocalStorageAdapter


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'local-queue.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_queued_job(session_factory, job_id: str = "job-local") -> None:
    with session_factory() as session:
        audio = AudioFile(
            id=f"audio-{job_id}",
            original_filename="demo.wav",
            content_type="audio/wav",
            file_size_bytes=8,
            duration_seconds=30.0,
            original_storage_key=f"jobs/{job_id}/original/demo.wav",
        )
        job = TranscriptionJob(
            id=job_id,
            audio_file=audio,
            status=JobStatus.QUEUED,
            stage=PipelineStage.QUEUED,
            progress=0,
        )
        session.add(job)
        session.commit()


def test_local_job_queue_runs_mock_pipeline_and_writes_exports(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'local-queue.db'}",
        storage_root=str(tmp_path / "storage"),
    )
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_queued_job(session_factory)

    queue = LocalJobQueue(
        settings=settings,
        session_factory=session_factory,
        runner_factory=lambda: LocalMockPipelineRunner(settings=settings, storage=storage),
    )

    queue.enqueue_transcription("job-local")
    queue.wait_for_all(timeout=5)
    assert queue._futures == []

    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-local"))
        drum_track = session.scalar(select(DrumTrack).where(DrumTrack.job_id == "job-local"))
        exports = session.scalars(select(ExportFile).where(ExportFile.job_id == "job-local")).all()

        assert job.status == JobStatus.COMPLETED
        assert job.stage == PipelineStage.COMPLETED
        assert job.progress == 100
        assert drum_track is not None
        assert drum_track.event_count == 4
        assert {export.type for export in exports} == {
            ExportFileType.MIDI,
            ExportFileType.MUSICXML,
            ExportFileType.PDF,
        }
        assert all(export.status == ExportFileStatus.AVAILABLE for export in exports)
        assert all(storage.exists(export.storage_key) for export in exports)


def test_local_job_queue_marks_runner_failure_as_failed(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'local-queue.db'}",
        storage_root=str(tmp_path / "storage"),
    )
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_queued_job(session_factory, "job-fail")
    queue = LocalJobQueue(
        settings=settings,
        session_factory=session_factory,
        runner_factory=lambda: LocalMockPipelineRunner(
            settings=settings,
            storage=storage,
            fail_stage=PipelineStage.DRUM_TRANSCRIPTION,
        ),
    )

    queue.enqueue_transcription("job-fail")
    queue.wait_for_all(timeout=5)
    assert queue._futures == []

    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-fail"))

        assert job.status == JobStatus.FAILED
        assert job.stage == PipelineStage.FAILED
        assert job.error_code == "DRUM_TRANSCRIPTION_FAILED"
        assert job.error_stage == PipelineStage.DRUM_TRANSCRIPTION.value
        assert job.failed_at is not None
