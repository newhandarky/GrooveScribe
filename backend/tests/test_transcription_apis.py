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
from app.storage.local import LocalStorageAdapter


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
