from __future__ import annotations

from sqlalchemy import select

from app.constants import JobStatus, PipelineStage, WorkerErrorCode
from app.db import transcription_jobs
from app.services.job_status_service import InvalidJobStateTransitionError, JobStatusService

from helpers import seed_queued_job, session_factory


def test_job_status_service_updates_lifecycle(tmp_path) -> None:
    factory = session_factory(tmp_path)
    with factory() as session:
        seed_queued_job(session)
        service = JobStatusService(session)

        service.mark_processing("job-1")
        service.update_stage("job-1", PipelineStage.SOURCE_SEPARATION.value, 25)
        service.mark_completed("job-1")
        session.commit()

        row = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert row["status"] == JobStatus.COMPLETED.value
        assert row["stage"] == PipelineStage.COMPLETED.value
        assert row["progress"] == 100
        assert row["started_at"] is not None
        assert row["completed_at"] is not None


def test_job_status_service_rejects_invalid_transition(tmp_path) -> None:
    factory = session_factory(tmp_path)
    with factory() as session:
        seed_queued_job(session)
        service = JobStatusService(session)

        try:
            service.mark_completed("job-1")
        except InvalidJobStateTransitionError as exc:
            assert exc.current_status == JobStatus.QUEUED.value
        else:
            raise AssertionError("expected invalid transition")


def test_job_status_service_marks_failed_with_required_error_fields(tmp_path) -> None:
    factory = session_factory(tmp_path)
    with factory() as session:
        seed_queued_job(session)
        service = JobStatusService(session)

        service.mark_failed(
            "job-1",
            error_code=WorkerErrorCode.PIPELINE_FAILED.value,
            error_message="failed",
            error_stage=PipelineStage.DRUM_TRANSCRIPTION.value,
            internal_error_ref="jobs/job-1/logs/pipeline.json",
        )
        session.commit()

        row = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        assert row["status"] == JobStatus.FAILED.value
        assert row["stage"] == PipelineStage.FAILED.value
        assert row["error_code"] == WorkerErrorCode.PIPELINE_FAILED.value
        assert row["error_stage"] == PipelineStage.DRUM_TRANSCRIPTION.value
        assert row["internal_error_ref"] == "jobs/job-1/logs/pipeline.json"
