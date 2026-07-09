from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models import AudioFile, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.job_queue import get_job_queue
from app.storage.dependencies import get_storage_adapter
from app.storage.local import LocalStorageAdapter

UNSAFE_TOKENS = (
    "/Users/",
    "/tmp/",
    "/private/tmp/",
    "/var/folders/",
    "Traceback",
    "stdout",
    "stderr",
    "raw command",
    "command_template",
)


class RecordingQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue_transcription(self, job_id: str, pipeline_config_id: str | None = None) -> None:
        self.enqueued.append(job_id)


def _session_factory(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _client(tmp_path: Path):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    queue = RecordingQueue()
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        storage_root=str(tmp_path / "storage"),
        job_queue_backend="noop",
    )
    app = create_app(settings)

    def override_db_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_storage_adapter] = lambda: storage
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), session_factory, storage, queue


def _seed_job(
    session: Session,
    *,
    job_id: str,
    status: JobStatus,
    stage: PipelineStage | None = None,
    created_at: datetime | None = None,
    storage_key: str | None = None,
    export_statuses: dict[ExportFileType, ExportFileStatus] | None = None,
    pipeline_mode: str | None = None,
    adtof_threshold_preset: str | None = None,
    tom_filter_preset: str | None = None,
    runtime_fallback_status: str | None = None,
) -> TranscriptionJob:
    key = storage_key or f"jobs/{job_id}/original/demo.wav"
    audio = AudioFile(
        id=f"audio-{job_id}",
        original_filename=f"{job_id}.wav",
        content_type="audio/wav",
        file_size_bytes=12,
        duration_seconds=6.0,
        original_storage_key=key,
    )
    job_kwargs = {}
    if created_at is not None:
        job_kwargs["created_at"] = created_at
    job = TranscriptionJob(
        id=job_id,
        audio_file=audio,
        status=status,
        stage=stage or _stage_for_status(status),
        progress=100 if status == JobStatus.COMPLETED else 45 if status == JobStatus.PROCESSING else 0,
        title=f"Title {job_id}",
        queued_at=created_at if status in {JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.COMPLETED} else None,
        completed_at=created_at + timedelta(minutes=2) if created_at and status == JobStatus.COMPLETED else None,
        failed_at=created_at + timedelta(minutes=2) if created_at and status in {JobStatus.FAILED, JobStatus.INTERRUPTED} else None,
        error_code="PIPELINE_FAILED" if status in {JobStatus.FAILED, JobStatus.INTERRUPTED} else None,
        error_message="音訊分析流程失敗，請稍後再試或重新上傳音檔。"
        if status in {JobStatus.FAILED, JobStatus.INTERRUPTED}
        else None,
        error_stage=PipelineStage.DRUM_TRANSCRIPTION.value
        if status in {JobStatus.FAILED, JobStatus.INTERRUPTED}
        else None,
        pipeline_mode=pipeline_mode,
        adtof_threshold_preset=adtof_threshold_preset,
        tom_filter_preset=tom_filter_preset,
        runtime_fallback_status=runtime_fallback_status,
        **job_kwargs,
    )
    session.add(job)
    for export_type, export_status in (export_statuses or {}).items():
        session.add(
            ExportFile(
                id=f"export-{job_id}-{export_type.value}",
                job=job,
                type=export_type,
                status=export_status,
                storage_key=f"jobs/{job_id}/exports/{export_type.value}",
                content_type="application/octet-stream",
                file_size_bytes=16 if export_status == ExportFileStatus.AVAILABLE else None,
            )
        )
    session.commit()
    return job


def _stage_for_status(status: JobStatus) -> PipelineStage:
    if status == JobStatus.COMPLETED:
        return PipelineStage.COMPLETED
    if status in {JobStatus.FAILED, JobStatus.INTERRUPTED}:
        return PipelineStage.FAILED
    if status == JobStatus.PROCESSING:
        return PipelineStage.DRUM_TRANSCRIPTION
    if status == JobStatus.UPLOADED:
        return PipelineStage.UPLOADED
    return PipelineStage.QUEUED


def test_lists_recent_jobs_with_redacted_summaries(tmp_path: Path) -> None:
    client, session_factory, _storage, _queue = _client(tmp_path)
    base = datetime(2026, 7, 4, tzinfo=UTC)
    with session_factory() as session:
        _seed_job(session, job_id="old", status=JobStatus.QUEUED, created_at=base)
        _seed_job(
            session,
            job_id="failed",
            status=JobStatus.FAILED,
            created_at=base + timedelta(minutes=1),
            export_statuses={ExportFileType.MIDI: ExportFileStatus.FAILED},
        )
        _seed_job(
            session,
            job_id="completed",
            status=JobStatus.COMPLETED,
            created_at=base + timedelta(minutes=2),
            export_statuses={
                ExportFileType.MIDI: ExportFileStatus.AVAILABLE,
                ExportFileType.MUSICXML: ExportFileStatus.AVAILABLE,
            },
        )

    response = client.get("/api/v1/transcriptions?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert [job["job_id"] for job in body["jobs"]] == ["completed", "failed"]
    assert body["jobs"][0]["pipeline_config"]["mode"] == "unknown"
    assert body["jobs"][0]["exports"] == {"midi": "available", "musicxml": "available"}
    assert body["jobs"][1]["error"] == {
        "code": "PIPELINE_FAILED",
        "message": "音訊分析流程失敗，請稍後再試或重新上傳音檔。",
        "stage": "drum_transcription",
        "retriable": True,
    }
    assert_public_safe(body)
    assert "storage_key" not in str(body)


def test_retry_creates_new_job_from_original_audio_without_mutating_source(tmp_path: Path) -> None:
    client, session_factory, storage, queue = _client(tmp_path)
    with session_factory() as session:
        source = _seed_job(session, job_id="failed", status=JobStatus.FAILED)
        storage.put_bytes(b"audio", source.audio_file.original_storage_key, "audio/wav")

    response = client.post("/api/v1/transcriptions/failed/retry")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"] != "failed"
    assert body["status_url"] == f"/api/v1/transcriptions/{body['job_id']}/status"
    assert queue.enqueued == [body["job_id"]]
    with session_factory() as session:
        source = session.get(TranscriptionJob, "failed")
        retry = session.get(TranscriptionJob, body["job_id"])
        assert source is not None
        assert retry is not None
        assert source.status == JobStatus.FAILED
        assert retry.status == JobStatus.QUEUED
        assert retry.stage == PipelineStage.QUEUED
        assert retry.audio_file_id == source.audio_file_id
        assert retry.source_job_id == source.id


def test_retry_copies_or_overrides_pipeline_config(tmp_path: Path) -> None:
    client, session_factory, storage, _queue = _client(tmp_path)
    with session_factory() as session:
        source = _seed_job(
            session,
            job_id="completed",
            status=JobStatus.COMPLETED,
            pipeline_mode="demo_mock",
            runtime_fallback_status="not_required",
        )
        storage.put_bytes(b"audio", source.audio_file.original_storage_key, "audio/wav")

    copy_response = client.post("/api/v1/transcriptions/completed/retry")
    override_response = client.post(
        "/api/v1/transcriptions/completed/retry",
        data={
            "pipeline_mode": "true_ai",
            "adtof_threshold_preset": "separated_v1",
            "tom_filter_preset": "tom_guard_v1",
        },
    )

    assert copy_response.status_code == 202
    assert override_response.status_code == 202
    with session_factory() as session:
        copied = session.get(TranscriptionJob, copy_response.json()["job_id"])
        overridden = session.get(TranscriptionJob, override_response.json()["job_id"])
        assert copied is not None
        assert overridden is not None
        assert copied.source_job_id == "completed"
        assert copied.pipeline_mode == "demo_mock"
        assert copied.runtime_fallback_status == "not_required"
        assert overridden.source_job_id == "completed"
        assert overridden.pipeline_mode == "true_ai"
        assert overridden.adtof_threshold_preset == "separated_v1"
        assert overridden.tom_filter_preset == "tom_guard_v1"
        assert overridden.runtime_fallback_status == "not_applied"


def test_retry_can_switch_true_ai_source_back_to_demo_mock(tmp_path: Path) -> None:
    client, session_factory, storage, _queue = _client(tmp_path)
    with session_factory() as session:
        source = _seed_job(
            session,
            job_id="true-ai-source",
            status=JobStatus.COMPLETED,
            pipeline_mode="true_ai",
            adtof_threshold_preset="separated_v1",
            tom_filter_preset="tom_guard_v1",
            runtime_fallback_status="not_applied",
        )
        storage.put_bytes(b"audio", source.audio_file.original_storage_key, "audio/wav")

    response = client.post(
        "/api/v1/transcriptions/true-ai-source/retry",
        data={"pipeline_mode": "demo_mock"},
    )

    assert response.status_code == 202
    with session_factory() as session:
        retry = session.get(TranscriptionJob, response.json()["job_id"])
        assert retry is not None
        assert retry.source_job_id == "true-ai-source"
        assert retry.pipeline_mode == "demo_mock"
        assert retry.adtof_threshold_preset is None
        assert retry.tom_filter_preset is None
        assert retry.runtime_fallback_status == "not_required"


def test_retry_rejects_public_unknown_pipeline_mode(tmp_path: Path) -> None:
    client, session_factory, storage, _queue = _client(tmp_path)
    with session_factory() as session:
        source = _seed_job(session, job_id="completed", status=JobStatus.COMPLETED)
        storage.put_bytes(b"audio", source.audio_file.original_storage_key, "audio/wav")

    response = client.post(
        "/api/v1/transcriptions/completed/retry",
        data={"pipeline_mode": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_retry_allows_completed_and_interrupted_jobs(tmp_path: Path) -> None:
    client, session_factory, storage, queue = _client(tmp_path)
    with session_factory() as session:
        completed = _seed_job(session, job_id="completed", status=JobStatus.COMPLETED)
        interrupted = _seed_job(session, job_id="interrupted", status=JobStatus.INTERRUPTED)
        storage.put_bytes(b"audio", completed.audio_file.original_storage_key, "audio/wav")
        storage.put_bytes(b"audio", interrupted.audio_file.original_storage_key, "audio/wav")

    assert client.post("/api/v1/transcriptions/completed/retry").status_code == 202
    assert client.post("/api/v1/transcriptions/interrupted/retry").status_code == 202
    assert len(queue.enqueued) == 2


def test_retry_rejects_active_jobs(tmp_path: Path) -> None:
    client, session_factory, storage, _queue = _client(tmp_path)
    with session_factory() as session:
        queued = _seed_job(session, job_id="queued", status=JobStatus.QUEUED)
        processing = _seed_job(session, job_id="processing", status=JobStatus.PROCESSING)
        storage.put_bytes(b"audio", queued.audio_file.original_storage_key, "audio/wav")
        storage.put_bytes(b"audio", processing.audio_file.original_storage_key, "audio/wav")

    for job_id in ("queued", "processing"):
        response = client.post(f"/api/v1/transcriptions/{job_id}/retry")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_JOB_STATE_TRANSITION"


def test_retry_missing_original_audio_returns_safe_artifact_error(tmp_path: Path) -> None:
    client, session_factory, _storage, queue = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="failed", status=JobStatus.FAILED)

    response = client.post("/api/v1/transcriptions/failed/retry")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
    assert queue.enqueued == []
    assert_public_safe(response.json())


def test_local_data_summary_is_dry_run_and_public_safe(tmp_path: Path) -> None:
    client, session_factory, _storage, _queue = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="known", status=JobStatus.COMPLETED)
    (tmp_path / "storage" / "jobs" / "known").mkdir(parents=True)
    (tmp_path / "storage" / "jobs" / "orphan").mkdir(parents=True)

    response = client.get("/api/v1/local-data/summary")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "schema_version": "1.0",
        "status": "dry_run",
        "dry_run": True,
        "execute_supported": False,
        "storage_root_name": "storage",
        "job_dir_count": 2,
        "database_status": "readable",
        "database_job_count": 1,
        "orphan_job_dir_count": 1,
        "warnings": [],
    }
    assert_public_safe(body)


def assert_public_safe(payload: object) -> None:
    text = str(payload)
    normalized = text.lower()
    for token in UNSAFE_TOKENS:
        assert token.lower() not in normalized
