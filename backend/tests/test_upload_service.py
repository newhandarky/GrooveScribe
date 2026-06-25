from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.base import Base
from app.models import AudioFile, TranscriptionJob
from app.models.enums import JobStatus, PipelineStage
from app.services.audio_metadata import AudioMetadata
from app.services.job_queue import NoopJobQueue
from app.services.upload_service import UploadService
from app.storage.errors import StorageWriteFailedError
from app.storage.local import LocalStorageAdapter


@dataclass
class FakeMetadataInspector:
    duration_seconds: float = 30.0

    def inspect(self, content: bytes, *, filename: str, content_type: str, timeout_seconds: int) -> AudioMetadata:
        return AudioMetadata(duration_seconds=self.duration_seconds, sample_rate=44100, channels=2)


class FailingStorage:
    def put_bytes(self, content: bytes, storage_key: str, content_type: str):
        raise StorageWriteFailedError("disk full at /tmp/internal")


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        storage_root=str(tmp_path / "storage"),
    )


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_upload_service_creates_job_audio_file_and_original_artifact(tmp_path) -> None:
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    service = UploadService(
        settings=settings,
        storage=storage,
        queue=NoopJobQueue(),
        metadata_inspector=FakeMetadataInspector(),
    )

    with _session() as session:
        result = service.create_upload_job(
            db=session,
            filename="demo.wav",
            content_type="audio/wav",
            content=b"fake-wav",
            title="Demo",
        )

        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == result.job_id))
        audio = session.scalar(select(AudioFile))

        assert result.status == JobStatus.QUEUED
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.stage == PipelineStage.QUEUED
        assert audio is not None
        assert audio.original_filename == "demo.wav"
        assert storage.exists(audio.original_storage_key) is True


def test_upload_service_rejects_invalid_file_type(tmp_path) -> None:
    service = UploadService(
        settings=_settings(tmp_path),
        storage=LocalStorageAdapter(tmp_path / "storage"),
        queue=NoopJobQueue(),
        metadata_inspector=FakeMetadataInspector(),
    )

    with _session() as session:
        try:
            service.create_upload_job(
                db=session,
                filename="notes.txt",
                content_type="text/plain",
                content=b"hello",
            )
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.INVALID_FILE_TYPE
        else:
            raise AssertionError("expected INVALID_FILE_TYPE")


def test_upload_service_rejects_audio_too_long(tmp_path) -> None:
    settings = _settings(tmp_path)
    service = UploadService(
        settings=settings,
        storage=LocalStorageAdapter(settings.storage_root),
        queue=NoopJobQueue(),
        metadata_inspector=FakeMetadataInspector(duration_seconds=settings.upload_max_duration_seconds + 1),
    )

    with _session() as session:
        try:
            service.create_upload_job(
                db=session,
                filename="long.wav",
                content_type="audio/wav",
                content=b"fake-wav",
            )
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.AUDIO_TOO_LONG
        else:
            raise AssertionError("expected AUDIO_TOO_LONG")


def test_enqueue_failure_marks_traceable_failed_job(tmp_path) -> None:
    settings = _settings(tmp_path)
    service = UploadService(
        settings=settings,
        storage=LocalStorageAdapter(settings.storage_root),
        queue=NoopJobQueue(should_fail=True),
        metadata_inspector=FakeMetadataInspector(),
    )

    with _session() as session:
        try:
            service.create_upload_job(
                db=session,
                filename="demo.wav",
                content_type="audio/wav",
                content=b"fake-wav",
            )
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.QUEUE_ENQUEUE_FAILED
        else:
            raise AssertionError("expected QUEUE_ENQUEUE_FAILED")

        job = session.scalar(select(TranscriptionJob))
        audio = session.scalar(select(AudioFile))

        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.stage == PipelineStage.FAILED
        assert job.error_code == ErrorCode.QUEUE_ENQUEUE_FAILED
        assert job.error_stage == PipelineStage.QUEUED.value
        assert job.failed_at is not None
        assert audio is not None


def test_storage_write_failure_marks_traceable_failed_job(tmp_path) -> None:
    settings = _settings(tmp_path)
    service = UploadService(
        settings=settings,
        storage=FailingStorage(),
        queue=NoopJobQueue(),
        metadata_inspector=FakeMetadataInspector(),
    )

    with _session() as session:
        try:
            service.create_upload_job(
                db=session,
                filename="demo.wav",
                content_type="audio/wav",
                content=b"fake-wav",
            )
        except StorageWriteFailedError:
            pass
        else:
            raise AssertionError("expected STORAGE_WRITE_FAILED")

        job = session.scalar(select(TranscriptionJob))
        audio = session.scalar(select(AudioFile))

        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.stage == PipelineStage.FAILED
        assert job.error_code == ErrorCode.STORAGE_WRITE_FAILED
        assert job.error_stage == PipelineStage.UPLOADED.value
        assert job.failed_at is not None
        assert audio is not None
