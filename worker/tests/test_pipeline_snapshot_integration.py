from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.config import WorkerSettings
from app.constants import JobStatus
from app.pipeline_runner import MockPipelineRunner
from app.storage import LocalWorkerStorage
from app.tasks.transcription import run_transcription_job

from helpers import seed_queued_job, session_factory


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mock_worker_output_can_be_read_by_pipeline_snapshot_cli(tmp_path) -> None:
    factory = session_factory(tmp_path)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker.db'}"
    storage_root = tmp_path / "storage"
    settings = WorkerSettings(storage_root=str(storage_root))
    storage = LocalWorkerStorage(settings.storage_root)

    with factory() as session:
        _add_backend_read_model_compatibility_columns(session)
        seed_queued_job(session)

    result = run_transcription_job(
        "job-1",
        session_factory=factory,
        runner_factory=lambda: MockPipelineRunner(settings=settings, storage=storage),
    )

    assert result["status"] == "completed"
    assert (storage_root / "jobs/job-1/audio/normalized.wav").is_file()
    assert (storage_root / "jobs/job-1/stems/drums.wav").is_file()
    assert (storage_root / "jobs/job-1/midi/raw_drum.mid").is_file()
    assert (storage_root / "jobs/job-1/midi/processed_drum.mid").is_file()
    assert (storage_root / "jobs/job-1/midi/drum_events.json").is_file()
    assert (storage_root / "jobs/job-1/notation/score.musicxml").is_file()
    assert (storage_root / "jobs/job-1/exports/score.pdf").is_file()
    assert (storage_root / "jobs/job-1/logs/pipeline.json").is_file()

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/read_pipeline_snapshot.py"),
            "--job-id",
            "job-1",
            "--database-url",
            database_url,
            "--storage-root",
            str(storage_root),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "backend")},
        check=True,
        capture_output=True,
        text=True,
    )
    snapshot = json.loads(completed.stdout)

    assert snapshot["job_id"] == "job-1"
    assert snapshot["status"] == JobStatus.COMPLETED.value
    assert snapshot["pipeline_log_found"] is True
    assert snapshot["completed_with_warning"] is True
    assert snapshot["mock_ai"] is True
    assert snapshot["pipeline_mode"] == "mock"
    assert snapshot["artifacts"]["normalized_audio"] == "jobs/job-1/audio/normalized.wav"
    assert snapshot["artifacts"]["drums_stem"] == "jobs/job-1/stems/drums.wav"
    assert snapshot["artifacts"]["raw_midi"] == "jobs/job-1/midi/raw_drum.mid"
    assert snapshot["artifacts"]["processed_midi"] == "jobs/job-1/midi/processed_drum.mid"
    assert snapshot["artifacts"]["drum_events"] == "jobs/job-1/midi/drum_events.json"
    assert snapshot["artifacts"]["musicxml"] == "jobs/job-1/notation/score.musicxml"
    assert snapshot["artifacts"]["pdf"] == "jobs/job-1/exports/score.pdf"
    assert [report["name"] for report in snapshot["stage_reports"]] == [
        "preprocessing",
        "source_separation",
        "stem_validation",
        "drum_transcription",
        "midi_post_processing",
        "notation_generation",
        "pdf_export",
    ]
    assert snapshot["stage_reports"][-1]["status"] == "completed_with_warning"
    assert snapshot["stage_reports"][-1]["report"]["pdf"]["warnings"] == ["mock_pdf_completed_with_warning"]
    assert "mock_pdf_completed_with_warning" in snapshot["warnings"]


def _add_backend_read_model_compatibility_columns(session) -> None:
    session.execute(text("ALTER TABLE audio_files ADD COLUMN user_id VARCHAR(36)"))
    session.execute(text("ALTER TABLE transcription_jobs ADD COLUMN user_id VARCHAR(36)"))
    session.commit()
