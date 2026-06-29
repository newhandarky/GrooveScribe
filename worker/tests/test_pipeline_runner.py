from __future__ import annotations

from sqlalchemy import select

from app.config import WorkerSettings
from app.constants import ExportFileStatus, JobStatus, PipelineStage
from app.db import audio_files, drum_tracks, export_files, transcription_jobs
from app.error_handling import PipelineStageError
from app.pipeline_runner import MockPipelineRunner
from app.storage import LocalWorkerStorage

from helpers import seed_queued_job, session_factory


def test_mock_pipeline_runner_completes_job_and_writes_metadata(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(database_url="sqlite+pysqlite:///:memory:", storage_root=str(tmp_path / "storage"))
    runner = MockPipelineRunner(settings=settings, storage=LocalWorkerStorage(settings.storage_root))

    with factory() as session:
        seed_queued_job(session)
        result = runner.run(session=session, job_id="job-1")
        session.commit()

        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        audio = session.execute(select(audio_files).where(audio_files.c.id == "audio-job-1")).mappings().one()
        track = session.execute(select(drum_tracks).where(drum_tracks.c.job_id == "job-1")).mappings().one()
        exports = session.execute(select(export_files).where(export_files.c.job_id == "job-1")).mappings().all()

        assert job["status"] == JobStatus.COMPLETED.value
        assert job["stage"] == PipelineStage.COMPLETED.value
        assert audio["normalized_storage_key"] == "jobs/job-1/audio/normalized.wav"
        assert track["processed_midi_storage_key"] == "jobs/job-1/midi/processed_drum.mid"
        assert {export["type"] for export in exports} == {"midi", "musicxml", "pdf"}
        assert {export["status"] for export in exports} == {ExportFileStatus.AVAILABLE.value}
        assert result.log_storage_key == "jobs/job-1/logs/pipeline.json"
        assert (tmp_path / "storage/jobs/job-1/logs/pipeline.json").is_file()


def test_mock_pipeline_runner_failure_preserves_stage_for_task_boundary(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(database_url="sqlite+pysqlite:///:memory:", storage_root=str(tmp_path / "storage"))
    runner = MockPipelineRunner(
        settings=settings,
        storage=LocalWorkerStorage(settings.storage_root),
        fail_stage=PipelineStage.DRUM_TRANSCRIPTION.value,
    )

    with factory() as session:
        seed_queued_job(session)
        try:
            runner.run(session=session, job_id="job-1")
        except PipelineStageError as exc:
            assert exc.stage == PipelineStage.DRUM_TRANSCRIPTION.value
            assert session.execute(
                select(transcription_jobs.c.stage).where(transcription_jobs.c.id == "job-1")
            ).scalar_one() == PipelineStage.DRUM_TRANSCRIPTION.value
        else:
            raise AssertionError("expected PipelineStageError")
