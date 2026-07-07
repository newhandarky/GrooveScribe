from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

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


def test_export_review_packet_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_review_packet.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--job-id" in result.stdout


def test_export_review_packet_rejects_repo_output_dir() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_review_packet.py",
            "--job-id",
            "job-1",
            "--output-dir",
            "review-packet-output",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "output_dir_must_be_outside_repo" in result.stdout
    assert_public_safe(result.stdout + result.stderr)


def test_export_review_packet_writes_redacted_json_markdown_and_zip(tmp_path: Path) -> None:
    database = tmp_path / "groovescribe.db"
    storage_root = tmp_path / "storage"
    output_dir = tmp_path / "packet"
    _seed_completed_job(database, storage_root)

    result = subprocess.run(
        [
            "backend/.venv/bin/python",
            "scripts/export_review_packet.py",
            "--job-id",
            "job-1",
            "--database",
            str(database),
            "--storage-root",
            str(storage_root),
            "--output-dir",
            str(output_dir),
            "--zip",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["status"] == "exported"
    assert summary["files"] == ["review_packet.json", "review_notes.md", "review_packet.zip"]
    packet_text = (output_dir / "review_packet.json").read_text(encoding="utf-8")
    notes_text = (output_dir / "review_notes.md").read_text(encoding="utf-8")
    with zipfile.ZipFile(output_dir / "review_packet.zip") as archive:
        assert sorted(archive.namelist()) == ["drums.mid", "review_notes.md", "review_packet.json", "score.musicxml"]
        zipped_packet_text = archive.read("review_packet.json").decode("utf-8")
    for payload in (result.stdout, packet_text, notes_text):
        for token in UNSAFE_TOKENS:
            assert token not in payload
    assert_public_safe(zipped_packet_text)
    packet = json.loads(packet_text)
    assert packet["manual_eval_seed"]["artifact_ref"] == "review:job-1"
    assert packet["manual_eval_seed"]["processed_drum_counts"] == {"kick": 2, "snare": 2}
    assert packet["quality"]["raw_note_histogram"] == {"35": 2, "38": 2}
    assert packet["redaction"] == {"status": "passed", "unsafe_token_count": 0}
    zipped_packet = json.loads(zipped_packet_text)
    assert zipped_packet["schema_version"] == packet["schema_version"]
    assert zipped_packet["status"] == packet["status"]
    assert zipped_packet["job"]["job_id"] == packet["job"]["job_id"]
    assert zipped_packet["exports"] == packet["exports"]
    assert zipped_packet["manual_eval_seed"] == packet["manual_eval_seed"]


def test_export_review_packet_failure_paths_are_redacted(tmp_path: Path) -> None:
    database = tmp_path / "groovescribe.db"
    storage_root = tmp_path / "storage"
    output_dir = tmp_path / "packet"
    _seed_completed_job(database, storage_root)

    missing = _run_export("missing-job", database, storage_root, output_dir)
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["error"] == "JOB_NOT_FOUND"
    assert_public_safe(missing.stdout + missing.stderr)

    _seed_processing_job(database)
    not_completed = _run_export("job-processing", database, storage_root, output_dir)
    assert not_completed.returncode == 1
    assert json.loads(not_completed.stdout)["error"] == "JOB_NOT_COMPLETED"
    assert_public_safe(not_completed.stdout + not_completed.stderr)

    bad_db = _run_export("job-1", tmp_path / "bad.db", storage_root, output_dir)
    assert bad_db.returncode == 1
    assert json.loads(bad_db.stdout)["error"] == "review_packet_export_failed"
    assert_public_safe(bad_db.stdout + bad_db.stderr)


def _run_export(job_id: str, database: Path, storage_root: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "backend/.venv/bin/python",
            "scripts/export_review_packet.py",
            "--job-id",
            job_id,
            "--database",
            str(database),
            "--storage-root",
            str(storage_root),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def assert_public_safe(payload: str) -> None:
    for token in UNSAFE_TOKENS:
        assert token not in payload


def _seed_completed_job(database: Path, storage_root: Path) -> None:
    seed_code = r'''
from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, "backend")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.storage.local import LocalStorageAdapter

database = Path(sys.argv[1])
storage_root = Path(sys.argv[2])
engine = create_engine(f"sqlite+pysqlite:///{database}")
Base.metadata.create_all(engine)
storage = LocalStorageAdapter(storage_root)
storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
storage.put_bytes(b"<score-partwise />", "jobs/job-1/notation/score.musicxml", "application/vnd.recordare.musicxml+xml")
storage.put_bytes(
    b"""{"status":"completed","quality":{"raw_event_count":4,"processed_event_count":4,"raw_note_histogram":{"35":2,"38":2,"/Users/private":1,"/tmp/foo":1,"Traceback":1},"processed_drum_counts":{"kick":2,"snare":2,"/Users/private":3,"/tmp/foo":4,"stdout":5,"command_template":6},"quality_flags":[],"warnings":[]},"validation":{"musicxml":{"available":true,"parseable":true,"error_code":null,"warnings":[]},"pdf":{"available":false,"optional":true,"openable":null,"error_code":"pdf_unavailable","warnings":["pdf_optional_unavailable"]}}}""",
    "jobs/job-1/logs/pipeline.json",
    "application/json",
)
with Session(engine) as session:
    audio = AudioFile(id="audio-1", original_filename="demo.wav", content_type="audio/wav", file_size_bytes=8, duration_seconds=30.0, original_storage_key="jobs/job-1/original/demo.wav")
    job = TranscriptionJob(id="job-1", audio_file=audio, status=JobStatus.COMPLETED, stage=PipelineStage.COMPLETED, progress=100, title="Demo", pipeline_version="local-first-v1", completed_at=datetime(2026, 7, 6, tzinfo=UTC))
    session.add(job)
    session.add(DrumTrack(id="track-1", job=job, processed_midi_storage_key="jobs/job-1/midi/processed_drum.mid", event_count=4, warnings=[]))
    session.add_all([
        ExportFile(id="export-midi", job=job, type=ExportFileType.MIDI, status=ExportFileStatus.AVAILABLE, storage_key="jobs/job-1/midi/processed_drum.mid", content_type="audio/midi", file_size_bytes=4),
        ExportFile(id="export-musicxml", job=job, type=ExportFileType.MUSICXML, status=ExportFileStatus.AVAILABLE, storage_key="jobs/job-1/notation/score.musicxml", content_type="application/vnd.recordare.musicxml+xml", file_size_bytes=18),
    ])
    session.commit()
'''
    result = subprocess.run(
        ["backend/.venv/bin/python", "-c", seed_code, str(database), str(storage_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _seed_processing_job(database: Path) -> None:
    seed_code = r'''
from pathlib import Path
import sys

sys.path.insert(0, "backend")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import AudioFile, TranscriptionJob
from app.models.enums import JobStatus, PipelineStage

database = Path(sys.argv[1])
engine = create_engine(f"sqlite+pysqlite:///{database}")
with Session(engine) as session:
    audio = AudioFile(id="audio-processing", original_filename="processing.wav", content_type="audio/wav", file_size_bytes=8, original_storage_key="jobs/job-processing/original/processing.wav")
    job = TranscriptionJob(id="job-processing", audio_file=audio, status=JobStatus.PROCESSING, stage=PipelineStage.DRUM_TRANSCRIPTION, progress=50, title="Processing")
    session.add(job)
    session.commit()
'''
    result = subprocess.run(
        ["backend/.venv/bin/python", "-c", seed_code, str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
