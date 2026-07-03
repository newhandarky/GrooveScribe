from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.transcriptions import get_upload_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.audio_metadata import AudioMetadata, AudioMetadataInspectionError
from app.services.job_queue import NoopJobQueue
from app.services.local_job_queue import LocalJobQueue
from app.services.local_pipeline_runner import LocalMockPipelineRunner
from app.services.pipeline_service import PipelineServiceRunner
from app.services.upload_service import UploadService
from app.storage.dependencies import get_storage_adapter
from app.storage.local import LocalStorageAdapter


@dataclass
class FakeMetadataInspector:
    duration_seconds: float = 30.0
    unreadable: bool = False

    def inspect(self, content: bytes, *, filename: str, content_type: str, timeout_seconds: int) -> AudioMetadata:
        if self.unreadable:
            raise AudioMetadataInspectionError("metadata unreadable")
        return AudioMetadata(duration_seconds=self.duration_seconds, sample_rate=44100, channels=2)


def _session_factory(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _client(tmp_path: Path, *, metadata_inspector: FakeMetadataInspector | None = None):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    app = create_app()

    def override_db_session():
        with session_factory() as session:
            yield session

    def override_upload_service():
        return UploadService(
            settings=Settings(database_url="sqlite+pysqlite:///:memory:", storage_root=str(tmp_path / "storage")),
            storage=storage,
            queue=NoopJobQueue(),
            metadata_inspector=metadata_inspector or FakeMetadataInspector(),
        )

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_storage_adapter] = lambda: storage
    app.dependency_overrides[get_upload_service] = override_upload_service
    return TestClient(app), session_factory, storage


def _client_with_local_queue(
    tmp_path: Path,
    *,
    fail_stage: PipelineStage | None = None,
    process_runner=None,
):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        storage_root=str(tmp_path / "storage"),
        job_queue_backend="local",
    )
    if process_runner is None:
        def runner_factory():
            return LocalMockPipelineRunner(
                settings=settings,
                storage=storage,
                fail_stage=fail_stage,
            )
    else:
        def runner_factory():
            return PipelineServiceRunner(
                settings=settings,
                storage=storage,
                process_runner=process_runner,
            )
    queue = LocalJobQueue(settings=settings, session_factory=session_factory, runner_factory=runner_factory)
    app = create_app()

    def override_db_session():
        with session_factory() as session:
            yield session

    def override_upload_service():
        return UploadService(
            settings=settings,
            storage=storage,
            queue=queue,
            metadata_inspector=FakeMetadataInspector(),
        )

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_storage_adapter] = lambda: storage
    app.dependency_overrides[get_upload_service] = override_upload_service
    return TestClient(app), session_factory, storage, queue


def _write_fake_pipeline_output(output_dir: Path) -> None:
    artifact_paths = {
        "normalized_audio": output_dir / "audio" / "normalized.wav",
        "drums_stem": output_dir / "stems" / "drums.wav",
        "raw_midi": output_dir / "midi" / "raw_drum.mid",
        "processed_midi": output_dir / "midi" / "processed_drum.mid",
        "drum_events": output_dir / "midi" / "drum_events.json",
        "musicxml": output_dir / "notation" / "score.musicxml",
        "pdf": output_dir / "exports" / "score.pdf",
    }
    for name, path in artifact_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{name}\n".encode("utf-8"))
    log_payload = {
        "schema_version": "1.0",
        "status": "completed",
        "artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "quality": {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "raw_note_histogram": {"35": 1, "47": 6},
            "processed_drum_counts": {"kick": 1, "tom": 6},
            "quality_flags": ["hihat_missing_likely", "mostly_tom_output"],
            "warnings": ["hihat_missing_likely", "mostly_tom_output"],
        },
        "stages": [
            {"name": "source_separation", "status": "completed", "report": {"separator": "mock"}},
            {"name": "drum_transcription", "status": "completed", "report": {"transcriber": "mock", "event_count": 4}},
            {
                "name": "midi_post_processing",
                "status": "completed",
                "report": {"output_event_count": 4, "estimated_bpm": 120.0, "time_signature": "4/4"},
            },
            {
                "name": "notation_generation",
                "status": "completed",
                "report": {"event_count": 4, "measure_count": 1, "pdf": {"status": "completed"}},
            },
        ],
    }
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs" / "pipeline.json").write_text(json.dumps(log_payload), encoding="utf-8")


def _seed_job(
    session: Session,
    *,
    job_id: str,
    status: JobStatus,
    stage: PipelineStage,
    export_types: tuple[ExportFileType, ...] = (),
) -> None:
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
        status=status,
        stage=stage,
        progress=100 if status == JobStatus.COMPLETED else 45 if status == JobStatus.PROCESSING else 0,
        title="Demo",
        queued_at=datetime(2026, 6, 25, tzinfo=UTC),
        started_at=datetime(2026, 6, 25, 0, 1, tzinfo=UTC) if status != JobStatus.QUEUED else None,
        completed_at=datetime(2026, 6, 25, 0, 2, tzinfo=UTC) if status == JobStatus.COMPLETED else None,
        failed_at=datetime(2026, 6, 25, 0, 3, tzinfo=UTC) if status == JobStatus.FAILED else None,
        error_code="PIPELINE_FAILED" if status == JobStatus.FAILED else None,
        error_message="音訊分析流程失敗，請稍後再試或重新上傳音檔。" if status == JobStatus.FAILED else None,
        error_stage=PipelineStage.DRUM_TRANSCRIPTION.value if status == JobStatus.FAILED else None,
    )
    session.add(job)
    if status == JobStatus.COMPLETED:
        session.add(
            DrumTrack(
                id=f"track-{job_id}",
                job=job,
                processed_midi_storage_key=f"jobs/{job_id}/midi/processed_drum.mid",
                event_count=4,
                warnings=[],
            )
        )
    for export_type in export_types:
        storage_key = {
            ExportFileType.MIDI: f"jobs/{job_id}/midi/processed_drum.mid",
            ExportFileType.MUSICXML: f"jobs/{job_id}/notation/score.musicxml",
            ExportFileType.PDF: f"jobs/{job_id}/exports/score.pdf",
        }[export_type]
        content_type = {
            ExportFileType.MIDI: "audio/midi",
            ExportFileType.MUSICXML: "application/vnd.recordare.musicxml+xml",
            ExportFileType.PDF: "application/pdf",
        }[export_type]
        session.add(
            ExportFile(
                id=f"export-{job_id}-{export_type.value}",
                job=job,
                type=export_type,
                status=ExportFileStatus.AVAILABLE,
                storage_key=storage_key,
                content_type=content_type,
                file_size_bytes=4,
            )
        )
    session.commit()


def test_upload_api_creates_db_rows_and_original_artifact(tmp_path: Path) -> None:
    client, session_factory, storage = _client(tmp_path)

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
        data={"title": "Demo"},
    )

    assert response.status_code == 202
    body = response.json()
    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == body["job_id"]))
        audio = session.scalar(select(AudioFile).where(AudioFile.id == job.audio_file_id))
        assert job.status == JobStatus.QUEUED
        assert job.stage == PipelineStage.QUEUED
        assert audio.original_filename == "demo.wav"
        assert storage.exists(audio.original_storage_key) is True


def test_upload_api_metadata_unreadable_error(tmp_path: Path) -> None:
    client, _session_factory, _storage = _client(tmp_path, metadata_inspector=FakeMetadataInspector(unreadable=True))

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AUDIO_METADATA_UNREADABLE"


def test_status_api_returns_all_core_states(tmp_path: Path) -> None:
    client, session_factory, _storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="job-queued", status=JobStatus.QUEUED, stage=PipelineStage.QUEUED)
        _seed_job(
            session,
            job_id="job-processing",
            status=JobStatus.PROCESSING,
            stage=PipelineStage.SOURCE_SEPARATION,
        )
        _seed_job(session, job_id="job-completed", status=JobStatus.COMPLETED, stage=PipelineStage.COMPLETED)
        _seed_job(session, job_id="job-failed", status=JobStatus.FAILED, stage=PipelineStage.FAILED)
        _seed_job(session, job_id="job-interrupted", status=JobStatus.INTERRUPTED, stage=PipelineStage.FAILED)

    expected = {
        "job-queued": "queued",
        "job-processing": "processing",
        "job-completed": "completed",
        "job-failed": "failed",
        "job-interrupted": "interrupted",
    }
    for job_id, status in expected.items():
        response = client.get(f"/api/v1/transcriptions/{job_id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == status
        if status == "failed":
            assert body["error"]["code"] == "PIPELINE_FAILED"
            assert body["error"]["retriable"] is True


def test_upload_api_default_local_queue_completes_without_celery(tmp_path: Path) -> None:
    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_fake_pipeline_output(output_dir)
        return subprocess.CompletedProcess(command, 0, stdout='{"status": "completed"}', stderr="")

    client, session_factory, _storage, queue = _client_with_local_queue(tmp_path, process_runner=fake_process)

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
        data={"title": "Demo"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    queue.wait_for_all(timeout=5)

    status_response = client.get(f"/api/v1/transcriptions/{job_id}/status")
    result_response = client.get(f"/api/v1/transcriptions/{job_id}")
    midi_response = client.get(f"/api/v1/transcriptions/{job_id}/download/midi")
    musicxml_response = client.get(f"/api/v1/transcriptions/{job_id}/download/musicxml")
    pdf_response = client.get(f"/api/v1/transcriptions/{job_id}/download/pdf")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert result_response.status_code == 200
    result_body = result_response.json()
    assert {export["type"] for export in result_body["exports"]} == {"midi", "musicxml", "pdf"}
    assert result_body["pipeline"]["quality"]["raw_event_count"] == 7
    assert result_body["pipeline"]["quality"]["processed_drum_counts"] == {"kick": 1, "tom": 6}
    assert "mostly_tom_output" in result_body["pipeline"]["quality"]["quality_flags"]
    assert "/tmp/" not in str(result_body["pipeline"])
    assert midi_response.status_code == 200
    assert musicxml_response.status_code == 200
    assert pdf_response.status_code == 200
    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        assert job.status == JobStatus.COMPLETED


def test_upload_api_local_queue_failure_marks_job_failed(tmp_path: Path) -> None:
    client, _session_factory, _storage, queue = _client_with_local_queue(
        tmp_path,
        fail_stage=PipelineStage.DRUM_TRANSCRIPTION,
    )

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    queue.wait_for_all(timeout=5)

    status_response = client.get(f"/api/v1/transcriptions/{job_id}/status")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "DRUM_TRANSCRIPTION_FAILED"
    assert body["error"]["stage"] == "drum_transcription"


def test_result_api_uses_audio_contract(tmp_path: Path) -> None:
    client, session_factory, storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(
            session,
            job_id="job-result",
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_types=(ExportFileType.MUSICXML,),
        )
    storage.put_bytes(b"<score-partwise />", "jobs/job-result/notation/score.musicxml", "application/vnd.recordare.musicxml+xml")

    response = client.get("/api/v1/transcriptions/job-result")

    assert response.status_code == 200
    body = response.json()
    assert "audio" in body
    assert "audio_file" not in body
    assert "pipeline_log" not in body
    assert "stage_reports" not in body
    assert body["audio"]["file_name"] == "demo.wav"
    assert body["preview"]["musicxml_url"] == "/api/v1/transcriptions/job-result/download/musicxml"


def test_download_api_returns_musicxml_and_pdf(tmp_path: Path) -> None:
    client, session_factory, storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(
            session,
            job_id="job-download",
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_types=(ExportFileType.MUSICXML, ExportFileType.PDF),
        )
    storage.put_bytes(b"<score-partwise />", "jobs/job-download/notation/score.musicxml", "application/vnd.recordare.musicxml+xml")
    storage.put_bytes(b"%PDF", "jobs/job-download/exports/score.pdf", "application/pdf")

    musicxml_response = client.get("/api/v1/transcriptions/job-download/download/musicxml")
    pdf_response = client.get("/api/v1/transcriptions/job-download/download/pdf")

    assert musicxml_response.status_code == 200
    assert musicxml_response.content == b"<score-partwise />"
    assert musicxml_response.headers["content-type"].startswith("application/vnd.recordare.musicxml+xml")
    assert pdf_response.status_code == 200
    assert pdf_response.content == b"%PDF"
    assert pdf_response.headers["content-type"].startswith("application/pdf")
