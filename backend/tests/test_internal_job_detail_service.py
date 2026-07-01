from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import ApiErrorException, ErrorCode
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.internal_job_detail_service import InternalJobDetailService
from app.storage.local import LocalStorageAdapter


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_job(
    session: Session,
    *,
    job_id: str = "job-1",
    status: JobStatus = JobStatus.COMPLETED,
    stage: PipelineStage = PipelineStage.COMPLETED,
    with_outputs: bool = True,
    source_separator: str | None = "mock",
    drum_transcriber: str | None = "mock",
) -> TranscriptionJob:
    audio = AudioFile(
        id=f"audio-{job_id}",
        original_filename="demo.wav",
        content_type="audio/wav",
        file_size_bytes=8,
        original_storage_key=f"jobs/{job_id}/original/demo.wav",
        normalized_storage_key=f"jobs/{job_id}/audio/normalized.wav" if with_outputs else None,
    )
    job = TranscriptionJob(
        id=job_id,
        audio_file=audio,
        status=status,
        stage=stage,
        progress=100 if status == JobStatus.COMPLETED else 60,
        source_separator=source_separator,
        drum_transcriber=drum_transcriber,
    )
    session.add(job)
    if with_outputs:
        session.add(
            DrumTrack(
                id=f"track-{job_id}",
                job=job,
                drums_stem_storage_key=f"jobs/{job_id}/stems/drums.wav",
                raw_midi_storage_key=f"jobs/{job_id}/midi/raw_drum.mid",
                processed_midi_storage_key=f"jobs/{job_id}/midi/processed_drum.mid",
                drum_events_storage_key=f"jobs/{job_id}/midi/drum_events.json",
                event_count=4,
                warnings=["mock_ai_enabled"],
            )
        )
        session.add_all(
            [
                ExportFile(
                    id=f"export-{job_id}-musicxml",
                    job=job,
                    type=ExportFileType.MUSICXML,
                    status=ExportFileStatus.AVAILABLE,
                    storage_key=f"jobs/{job_id}/notation/score.musicxml",
                    content_type="application/vnd.recordare.musicxml+xml",
                ),
                ExportFile(
                    id=f"export-{job_id}-pdf",
                    job=job,
                    type=ExportFileType.PDF,
                    status=ExportFileStatus.AVAILABLE,
                    storage_key=f"jobs/{job_id}/exports/score.pdf",
                    content_type="application/pdf",
                ),
            ]
        )
    session.commit()
    return job


def _write_pipeline_log(storage: LocalStorageAdapter, job_id: str, payload: dict) -> None:
    storage.put_bytes(
        json.dumps(payload).encode("utf-8"),
        f"jobs/{job_id}/logs/pipeline.json",
        "application/json",
    )


def test_internal_job_detail_reads_pipeline_stage_reports_and_pdf_warning(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _session() as session:
        _create_job(session, job_id="job-1")
        _write_pipeline_log(
            storage,
            "job-1",
            {
                "job_id": "job-1",
                "stage_reports": [
                    {
                        "name": "pdf_export",
                        "status": "completed_with_warning",
                        "artifacts": {"pdf": "jobs/job-1/exports/score.pdf"},
                        "report": {
                            "pdf": {
                                "status": "completed_with_warning",
                                "warnings": ["mock_pdf_completed_with_warning"],
                            }
                        },
                    }
                ],
            },
        )

        result = InternalJobDetailService(storage=storage).get_pipeline_snapshot(session, "job-1")

        assert result.pipeline_log_found is True
        assert result.status == "completed"
        assert result.failed_stage is None
        assert result.completed_with_warning is True
        assert result.error is None
        assert result.mock_ai is True
        assert result.pipeline_mode == "mock"
        assert result.artifacts["drum_events"] == "jobs/job-1/midi/drum_events.json"
        assert result.artifacts["pipeline_log"] == "jobs/job-1/logs/pipeline.json"
        assert result.stage_reports[0].status == "completed_with_warning"
        assert result.warnings == ["mock_ai_enabled", "mock_pdf_completed_with_warning"]


def test_internal_job_detail_reads_failed_stage_error_from_pipeline_log(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _session() as session:
        _create_job(
            session,
            job_id="job-failed",
            status=JobStatus.FAILED,
            stage=PipelineStage.FAILED,
            with_outputs=False,
            source_separator=None,
            drum_transcriber=None,
        )
        _write_pipeline_log(
            storage,
            "job-failed",
            {
                "job_id": "job-failed",
                "stage_reports": [
                    {
                        "name": "drum_transcription",
                        "status": "failed",
                        "error": {
                            "code": "DRUM_TRANSCRIPTION_FAILED",
                            "message": "adtof failed",
                            "stage": "drum_transcription",
                        },
                    }
                ],
            },
        )

        result = InternalJobDetailService(storage=storage).get_pipeline_snapshot(session, "job-failed")

        assert result.pipeline_log_found is True
        assert result.failed_stage == "drum_transcription"
        assert result.error is not None
        assert result.error.code == "DRUM_TRANSCRIPTION_FAILED"
        assert result.error.message == "adtof failed"
        assert result.completed_with_warning is False


def test_internal_job_detail_has_clear_empty_state_when_pipeline_log_is_missing(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _session() as session:
        _create_job(session, job_id="job-no-log", status=JobStatus.QUEUED, stage=PipelineStage.QUEUED, with_outputs=False)

        result = InternalJobDetailService(storage=storage).get_pipeline_snapshot(session, "job-no-log")

        assert result.pipeline_log_found is False
        assert result.stage_reports == []
        assert result.warnings == []
        assert result.completed_with_warning is False
        assert result.error is None
        assert result.artifacts == {"original_audio": "jobs/job-no-log/original/demo.wav"}


def test_internal_job_detail_rejects_missing_job(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _session() as session:
        try:
            InternalJobDetailService(storage=storage).get_pipeline_snapshot(session, "missing")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.JOB_NOT_FOUND
        else:
            raise AssertionError("expected JOB_NOT_FOUND")
