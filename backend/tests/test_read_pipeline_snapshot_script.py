from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.storage.local import LocalStorageAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/read_pipeline_snapshot.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("read_pipeline_snapshot_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}"


def _prepare_db(database_url: str) -> Session:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_job(
    session: Session,
    *,
    job_id: str,
    status: JobStatus = JobStatus.COMPLETED,
    stage: PipelineStage = PipelineStage.COMPLETED,
    with_outputs: bool = True,
) -> None:
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
        source_separator="mock" if with_outputs else None,
        drum_transcriber="mock" if with_outputs else None,
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


def test_read_pipeline_snapshot_cli_outputs_stage_reports_and_pdf_warning(tmp_path, capsys) -> None:
    module = _load_script_module()
    database_url = _database_url(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _prepare_db(database_url) as session:
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
                    "report": {"pdf": {"status": "completed_with_warning", "warnings": ["renderer_nonzero_exit"]}},
                }
            ],
        },
    )

    exit_code = module.main(
        [
            "--job-id",
            "job-1",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage.root),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["job_id"] == "job-1"
    assert body["pipeline_log_found"] is True
    assert body["completed_with_warning"] is True
    assert body["stage_reports"][0]["status"] == "completed_with_warning"
    assert body["warnings"] == ["mock_ai_enabled", "renderer_nonzero_exit"]
    assert body["mock_ai"] is True
    assert body["pipeline_mode"] == "mock"


def test_read_pipeline_snapshot_cli_outputs_failed_stage_error(tmp_path, capsys) -> None:
    module = _load_script_module()
    database_url = _database_url(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _prepare_db(database_url) as session:
        _create_job(session, job_id="job-failed", status=JobStatus.FAILED, stage=PipelineStage.FAILED, with_outputs=False)
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

    exit_code = module.main(
        [
            "--job-id",
            "job-failed",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage.root),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["failed_stage"] == "drum_transcription"
    assert body["error"]["code"] == "DRUM_TRANSCRIPTION_FAILED"
    assert body["error"]["message"] == "adtof failed"
    assert body["completed_with_warning"] is False


def test_read_pipeline_snapshot_cli_outputs_missing_pipeline_log_state(tmp_path, capsys) -> None:
    module = _load_script_module()
    database_url = _database_url(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _prepare_db(database_url) as session:
        _create_job(session, job_id="job-no-log", status=JobStatus.QUEUED, stage=PipelineStage.QUEUED, with_outputs=False)

    exit_code = module.main(
        [
            "--job-id",
            "job-no-log",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage.root),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["pipeline_log_found"] is False
    assert body["stage_reports"] == []
    assert body["warnings"] == []
    assert body["artifacts"] == {"original_audio": "jobs/job-no-log/original/demo.wav"}


def test_read_pipeline_snapshot_cli_redacts_by_default_and_raw_is_explicit(tmp_path, capsys) -> None:
    module = _load_script_module()
    database_url = _database_url(tmp_path)
    storage = LocalStorageAdapter(tmp_path / "storage")
    with _prepare_db(database_url) as session:
        _create_job(session, job_id="job-redacted", status=JobStatus.FAILED, stage=PipelineStage.FAILED, with_outputs=False)
    _write_pipeline_log(
        storage,
        "job-redacted",
        {
            "job_id": "job-redacted",
            "stage_reports": [
                {
                    "name": "drum_transcription",
                    "status": "failed",
                    "report": {
                        "command_template": "/Users/dev/private/adtof --input {input}",
                        "stderr": "Traceback at /tmp/private",
                    },
                    "error": {
                        "code": "DRUM_TRANSCRIPTION_FAILED",
                        "message": "/Users/dev/private/adtof failed",
                    },
                }
            ],
        },
    )

    default_exit_code = module.main(
        [
            "--job-id",
            "job-redacted",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage.root),
        ]
    )
    default_output = capsys.readouterr().out

    raw_exit_code = module.main(
        [
            "--job-id",
            "job-redacted",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage.root),
            "--raw",
        ]
    )
    raw_output = capsys.readouterr().out

    assert default_exit_code == 0
    assert raw_exit_code == 0
    assert "/Users/dev/private" not in default_output
    assert "Traceback" not in default_output
    assert "[redacted]" in default_output
    assert "/Users/dev/private" in raw_output
