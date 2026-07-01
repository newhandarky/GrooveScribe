from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.storage.dependencies import get_storage_adapter
from app.storage.local import LocalStorageAdapter


def _session_factory(tmp_path: Path):
    db_path = tmp_path / "internal.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _client(
    tmp_path: Path,
    *,
    enabled: bool = True,
    token: str | None = "dev-secret",
) -> tuple[TestClient, sessionmaker[Session], LocalStorageAdapter]:
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        storage_root=str(storage.root),
        internal_api_enabled=enabled,
        internal_api_token=token,
        internal_api_token_label="dev-internal",
    )
    app = create_app(settings)

    def override_db_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_storage_adapter] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), session_factory, storage


def _seed_job(
    session: Session,
    *,
    job_id: str,
    status: JobStatus = JobStatus.COMPLETED,
    stage: PipelineStage = PipelineStage.COMPLETED,
    with_outputs: bool = True,
    with_db_error: bool = False,
) -> None:
    audio = AudioFile(
        id=f"audio-{job_id}",
        original_filename="demo.wav",
        content_type="audio/wav",
        file_size_bytes=8,
        duration_seconds=30.0,
        original_storage_key=f"jobs/{job_id}/original/demo.wav",
        normalized_storage_key=f"jobs/{job_id}/audio/normalized.wav" if with_outputs else None,
    )
    job = TranscriptionJob(
        id=job_id,
        audio_file=audio,
        status=status,
        stage=stage,
        progress=100 if status == JobStatus.COMPLETED else 60,
        title="Internal",
        queued_at=datetime(2026, 7, 1, tzinfo=UTC),
        source_separator="mock" if with_outputs else None,
        drum_transcriber="mock" if with_outputs else None,
        error_code="PIPELINE_FAILED" if with_db_error else None,
        error_message="safe failed message" if with_db_error else None,
        error_stage=PipelineStage.DRUM_TRANSCRIPTION.value if with_db_error else None,
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
        session.add(
            ExportFile(
                id=f"export-{job_id}-pdf",
                job=job,
                type=ExportFileType.PDF,
                status=ExportFileStatus.AVAILABLE,
                storage_key=f"jobs/{job_id}/exports/score.pdf",
                content_type="application/pdf",
            )
        )
    session.commit()


def _write_pipeline_log(storage: LocalStorageAdapter, job_id: str, payload: dict) -> None:
    storage.put_bytes(
        json.dumps(payload).encode("utf-8"),
        f"jobs/{job_id}/logs/pipeline.json",
        "application/json",
    )


def _auth_headers(token: str = "dev-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "x-request-id": "request-1"}


def test_internal_pipeline_snapshot_route_is_not_registered_when_disabled(tmp_path: Path) -> None:
    client, _session_factory, _storage = _client(tmp_path, enabled=False)

    response = client.get("/internal/jobs/job-1/pipeline-snapshot")

    assert response.status_code == 404


def test_internal_pipeline_snapshot_route_is_hidden_from_openapi_when_enabled(tmp_path: Path) -> None:
    client, _session_factory, _storage = _client(tmp_path, enabled=True)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/internal/jobs/{job_id}/pipeline-snapshot" not in response.json()["paths"]


def test_internal_pipeline_snapshot_auth_rejects_missing_and_wrong_token(tmp_path: Path, caplog) -> None:
    client, _session_factory, _storage = _client(tmp_path)

    with caplog.at_level(logging.INFO, logger="groovescribe.internal"):
        missing = client.get("/internal/jobs/job-1/pipeline-snapshot")
        wrong = client.get("/internal/jobs/job-1/pipeline-snapshot", headers=_auth_headers("wrong"))

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert "dev-secret" not in caplog.text
    assert '"status_code": 401' in caplog.text
    assert '"status_code": 403' in caplog.text


def test_internal_pipeline_snapshot_returns_redacted_stage_reports_and_pdf_warning(tmp_path: Path, caplog) -> None:
    client, session_factory, storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="job-1")
    _write_pipeline_log(
        storage,
        "job-1",
        {
            "job_id": "job-1",
            "artifacts": {
                "drum_events": "jobs/job-1/midi/drum_events.json",
                "debug_file": "/tmp/groovescribe-debug/raw.json",
            },
            "stage_reports": [
                {
                    "name": "pdf_export",
                    "status": "completed_with_warning",
                    "runtime_seconds": 0.12,
                    "artifacts": {"pdf": "jobs/job-1/exports/score.pdf", "local_pdf": "/Users/dev/score.pdf"},
                    "report": {
                        "pdf": {
                            "status": "completed_with_warning",
                            "warnings": ["renderer_nonzero_exit"],
                        },
                        "renderer": "mock",
                        "command_template": "musescore {input} --export-to {output}",
                        "checkpoint_path": "/Users/dev/model.ckpt",
                        "stderr": "Traceback: secret stack",
                    },
                }
            ],
        },
    )

    with caplog.at_level(logging.INFO, logger="groovescribe.internal"):
        response = client.get("/internal/jobs/job-1/pipeline-snapshot", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    assert body["job_id"] == "job-1"
    assert body["status"] == "completed"
    assert body["pipeline_log_found"] is True
    assert body["completed_with_warning"] is True
    assert body["mock_ai"] is True
    assert body["pipeline_mode"] == "mock"
    assert body["artifacts"]["drum_events"] == "jobs/job-1/midi/drum_events.json"
    assert body["artifacts"]["debug_file"] == "[redacted]"
    assert body["stage_reports"][0]["artifacts"]["local_pdf"] == "[redacted]"
    assert body["stage_reports"][0]["report"]["command_template"] == "[redacted]"
    assert body["stage_reports"][0]["report"]["checkpoint_path"] == "[redacted]"
    assert body["stage_reports"][0]["report"]["stderr"] == "[redacted]"
    assert "/Users/" not in serialized
    assert "/tmp/" not in serialized
    assert "musescore {input}" not in serialized
    assert "secret stack" not in serialized
    assert "dev-secret" not in caplog.text
    assert '"event": "internal_pipeline_snapshot_read"' in caplog.text
    assert '"status_code": 200' in caplog.text


def test_internal_pipeline_snapshot_returns_failed_stage_error(tmp_path: Path) -> None:
    client, session_factory, storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="job-failed", status=JobStatus.FAILED, stage=PipelineStage.FAILED, with_outputs=False)
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
                        "message": "safe transcriber failed",
                        "stage": "drum_transcription",
                    },
                }
            ],
        },
    )

    response = client.get("/internal/jobs/job-failed/pipeline-snapshot", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["failed_stage"] == "drum_transcription"
    assert body["error"] == {
        "code": "DRUM_TRANSCRIPTION_FAILED",
        "message": "safe transcriber failed",
        "stage": "drum_transcription",
    }


def test_internal_pipeline_snapshot_returns_missing_pipeline_log_state(tmp_path: Path) -> None:
    client, session_factory, _storage = _client(tmp_path)
    with session_factory() as session:
        _seed_job(session, job_id="job-no-log", status=JobStatus.QUEUED, stage=PipelineStage.QUEUED, with_outputs=False)

    response = client.get("/internal/jobs/job-no-log/pipeline-snapshot", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_log_found"] is False
    assert body["stage_reports"] == []
    assert body["artifacts"] == {"original_audio": "jobs/job-no-log/original/demo.wav"}


def test_public_transcription_result_contract_does_not_expose_internal_snapshot(tmp_path: Path) -> None:
    client, session_factory, _storage = _client(tmp_path, enabled=True)
    with session_factory() as session:
        _seed_job(session, job_id="job-public")

    response = client.get("/api/v1/transcriptions/job-public")

    assert response.status_code == 200
    body = response.json()
    assert "pipeline_log" not in body
    assert "stage_reports" not in body
    assert "completed_with_warning" not in body
    assert "pipeline_log_found" not in body
