from __future__ import annotations

from sqlalchemy import select

from app.config import WorkerSettings
from app.constants import JobStatus, PipelineStage, WorkerErrorCode
from app.db import transcription_jobs
from app.pipeline_runner import MockPipelineRunner
from app.services.job_status_service import JobStatusService
from app.storage import LocalWorkerStorage
import app.tasks.transcription as transcription_module
from app.tasks.transcription import run_transcription_job, transcribe_audio

from helpers import seed_queued_job, session_factory


def test_transcription_task_is_registered() -> None:
    assert transcribe_audio.name == "worker.transcription.transcribe_audio"


def test_run_transcription_job_completes_mock_pipeline(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(storage_root=str(tmp_path / "storage"))
    with factory() as session:
        seed_queued_job(session)

    result = run_transcription_job(
        "job-1",
        session_factory=factory,
        runner_factory=lambda: MockPipelineRunner(
            settings=settings,
            storage=LocalWorkerStorage(settings.storage_root),
        ),
    )

    with factory() as session:
        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert result["status"] == "completed"
        assert job["status"] == JobStatus.COMPLETED.value


def test_run_transcription_job_marks_stage_failure(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(storage_root=str(tmp_path / "storage"))
    with factory() as session:
        seed_queued_job(session)

    result = run_transcription_job(
        "job-1",
        session_factory=factory,
        runner_factory=lambda: MockPipelineRunner(
            settings=settings,
            storage=LocalWorkerStorage(settings.storage_root),
            fail_stage=PipelineStage.DRUM_TRANSCRIPTION.value,
        ),
    )

    with factory() as session:
        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert result["status"] == "failed"
        assert job["status"] == JobStatus.FAILED.value
        assert job["stage"] == PipelineStage.FAILED.value
        assert job["error_code"] == WorkerErrorCode.DRUM_TRANSCRIPTION_FAILED.value
        assert job["error_stage"] == PipelineStage.DRUM_TRANSCRIPTION.value
        assert job["internal_error_ref"] == "jobs/job-1/logs/pipeline.json"
        assert "stage_started" in (tmp_path / "storage/jobs/job-1/logs/pipeline.json").read_text()


def test_run_transcription_job_marks_timeout_failed(tmp_path) -> None:
    factory = session_factory(tmp_path)
    storage = LocalWorkerStorage(tmp_path / "storage")

    class TimeoutRunner:
        def __init__(self) -> None:
            self.storage = storage

        def run(self, *, session, job_id: str, pipeline_config_id=None):
            service = JobStatusService(session)
            service.mark_processing(job_id)
            service.update_stage(job_id, PipelineStage.SOURCE_SEPARATION.value, 25)
            raise TimeoutError("worker timed out")

    with factory() as session:
        seed_queued_job(session)

    result = run_transcription_job("job-1", session_factory=factory, runner_factory=TimeoutRunner)

    with factory() as session:
        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert result["status"] == "failed"
        assert job["status"] == JobStatus.FAILED.value
        assert job["error_code"] == WorkerErrorCode.WORKER_TIMEOUT.value
        assert job["error_stage"] == PipelineStage.SOURCE_SEPARATION.value


def test_run_transcription_job_handles_missing_job(tmp_path) -> None:
    factory = session_factory(tmp_path)

    result = run_transcription_job("missing", session_factory=factory)

    assert result == {"job_id": "missing", "status": "not_found"}


def test_celery_task_run_consumes_seeded_job(tmp_path, monkeypatch) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(storage_root=str(tmp_path / "storage"))

    class TestRunner(MockPipelineRunner):
        def __init__(self):
            super().__init__(settings=settings, storage=LocalWorkerStorage(settings.storage_root))

    monkeypatch.setattr(transcription_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(transcription_module, "MockPipelineRunner", TestRunner)

    with factory() as session:
        seed_queued_job(session)

    result = transcribe_audio.run("job-1")

    with factory() as session:
        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert result["status"] == "completed"
        assert job["status"] == JobStatus.COMPLETED.value
