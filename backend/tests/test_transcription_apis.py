from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.download_service import DownloadService
from app.services.job_query_service import JobQueryService
from app.services.result_service import ResultService
from app.storage.keys import build_job_artifact_key
from app.storage.local import LocalStorageAdapter
from app.storage.types import ArtifactType


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_job(
    session: Session,
    *,
    status: JobStatus = JobStatus.QUEUED,
    stage: PipelineStage = PipelineStage.QUEUED,
    export_status: ExportFileStatus | None = None,
    export_type: ExportFileType = ExportFileType.MIDI,
    storage_key: str = "jobs/job-1/midi/processed_drum.mid",
) -> TranscriptionJob:
    audio = AudioFile(
        id="audio-1",
        original_filename="demo.wav",
        content_type="audio/wav",
        file_size_bytes=8,
        duration_seconds=30.0,
        original_storage_key="jobs/job-1/original/demo.wav",
    )
    job = TranscriptionJob(
        id="job-1",
        audio_file=audio,
        status=status,
        stage=stage,
        progress=100 if status == JobStatus.COMPLETED else 0,
        title="Demo",
    )
    session.add(job)
    if status == JobStatus.COMPLETED:
        session.add(
            DrumTrack(
                id="track-1",
                job=job,
                processed_midi_storage_key="jobs/job-1/midi/processed_drum.mid",
                event_count=4,
                warnings=[],
            )
        )
    if export_status is not None:
        session.add(
            ExportFile(
                id="export-1",
                job=job,
                type=export_type,
                status=export_status,
                storage_key=storage_key,
                content_type="audio/midi" if export_type == ExportFileType.MIDI else "application/octet-stream",
                file_size_bytes=4,
            )
        )
    session.commit()
    return job


def test_job_status_service_returns_stage_message() -> None:
    with _session() as session:
        _create_job(session)
        service = JobQueryService()

        job = service.get_job_or_raise(session, "job-1")

        assert job.status == JobStatus.QUEUED
        assert service.stage_message(job) == "任務已排隊，等待開始分析。"


def test_job_status_service_not_found_raises_job_not_found() -> None:
    with _session() as session:
        service = JobQueryService()

        try:
            service.get_job_or_raise(session, "missing")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.JOB_NOT_FOUND
        else:
            raise AssertionError("expected JOB_NOT_FOUND")


def test_job_status_failed_error_payload_includes_retriable() -> None:
    with _session() as session:
        job = _create_job(session, status=JobStatus.FAILED, stage=PipelineStage.FAILED)
        job.error_code = ErrorCode.PIPELINE_FAILED
        job.error_message = "音訊分析流程失敗，請稍後再試或重新上傳音檔。"
        job.error_stage = PipelineStage.DRUM_TRANSCRIPTION.value
        session.commit()
        service = JobQueryService()

        error = service.error_payload(job)

        assert error == {
            "code": ErrorCode.PIPELINE_FAILED,
            "message": "音訊分析流程失敗，請稍後再試或重新上傳音檔。",
            "stage": PipelineStage.DRUM_TRANSCRIPTION.value,
            "retriable": True,
        }


def test_result_service_returns_completed_job_with_related_metadata() -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings())

        job = service.get_completed_result(session, "job-1")

        assert job.audio_file.original_filename == "demo.wav"
        assert job.drum_track.event_count == 4
        assert service.download_url(job.id, "midi") == "/api/v1/transcriptions/job-1/download/midi"


def test_result_service_builds_redacted_pipeline_summary(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "stages": [
            {
              "name": "midi_post_processing",
              "status": "completed",
              "runtime_seconds": 1.25,
              "report": {
                "warnings": ["too_few_events", "/Users/private/path"]
              }
            }
          ],
          "artifacts": {"processed_midi": "jobs/job-1/midi/processed_drum.mid"}
          ,
          "quality": {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "raw_note_histogram": {"35": 1, "47": 6},
            "processed_drum_counts": {"kick": 1, "tom": 6},
            "duration_seconds": 12.5,
            "tempo_bpm": 118.2,
            "estimated_measure_count": 6,
            "quality_flags": ["hihat_missing_likely", "mostly_tom_output", "/tmp/private"],
            "warnings": ["hihat_missing_likely", "stderr leaked"]
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        job = _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings(), storage=storage)

        summary = service.pipeline_summary(job)

        assert summary["pipeline_log_available"] is True
        assert summary["mode"] == "unknown"
        assert summary["stages"] == [
            {
                "name": "midi_post_processing",
                "status": "completed",
                "runtime_seconds": 1.25,
                "warnings": ["too_few_events"],
            }
        ]
        assert summary["artifacts"][0]["type"] == "midi"
        assert summary["quality"] == {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "raw_note_histogram": {"35": 1, "47": 6},
            "processed_drum_counts": {"kick": 1, "tom": 6},
            "duration_seconds": 12.5,
            "tempo_bpm": 118.2,
            "estimated_measure_count": 6,
            "quality_flags": ["hihat_missing_likely", "mostly_tom_output"],
            "warnings": ["hihat_missing_likely"],
        }
        assert "/Users/" not in str(summary)
        assert "/tmp/" not in str(summary)
        assert "stderr" not in str(summary)


def test_result_service_quality_fallback_keeps_warning_and_flag_contract_separate(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "stages": [
            {
              "name": "midi_post_processing",
              "status": "completed",
              "runtime_seconds": 1.25,
              "report": {
                "input_event_count": 12,
                "output_event_count": 6,
                "raw_note_histogram": {"35": 2, "47": 10},
                "processed_drum_counts": {"kick": 2, "tom": 4},
                "estimated_bpm": 120,
                "warnings": ["too_few_events", "high_drop_ratio", "mock_ai_enabled"]
              }
            }
          ],
          "artifacts": {"processed_midi": "jobs/job-1/midi/processed_drum.mid"}
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        job = _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings(), storage=storage)

        summary = service.pipeline_summary(job)

        assert summary["quality"]["quality_flags"] == ["too_few_events"]
        assert summary["quality"]["warnings"] == ["high_drop_ratio", "mock_ai_enabled", "too_few_events"]


def test_result_service_rejects_non_completed_job() -> None:
    with _session() as session:
        _create_job(session, status=JobStatus.PROCESSING, stage=PipelineStage.SOURCE_SEPARATION)
        service = ResultService(settings=Settings())

        try:
            service.get_completed_result(session, "job-1")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.JOB_NOT_COMPLETED
        else:
            raise AssertionError("expected JOB_NOT_COMPLETED")


def test_download_service_opens_available_export(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = DownloadService(storage=storage)

        artifact = service.open_export(session, job_id="job-1", export_type="midi")

        try:
            assert artifact.content_type == "audio/midi"
            assert artifact.filename == "processed_drum.mid"
            assert artifact.reader.read() == b"midi"
        finally:
            artifact.reader.close()


def test_download_service_rejects_pending_export(tmp_path) -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.PENDING,
        )
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="midi")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_READY
        else:
            raise AssertionError("expected EXPORT_NOT_READY")


def test_download_service_rejects_missing_export(tmp_path) -> None:
    with _session() as session:
        _create_job(session, status=JobStatus.COMPLETED, stage=PipelineStage.COMPLETED)
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="pdf")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_FOUND
        else:
            raise AssertionError("expected EXPORT_NOT_FOUND")


def test_download_service_maps_missing_storage_artifact_to_export_not_found(tmp_path) -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="midi")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_FOUND
        else:
            raise AssertionError("expected EXPORT_NOT_FOUND")
