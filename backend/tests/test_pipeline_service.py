from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.local_pipeline_runner import LocalPipelineRunnerError
from app.services.pipeline_service import PipelineServiceRunner
from app.storage.local import LocalStorageAdapter


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}",
        "storage_root": str(tmp_path / "storage"),
        "ai_python_path": "/opt/groovescribe-ai/bin/python",
        "pipeline_timeout_seconds": 123,
    }
    values.update(overrides)
    return Settings(**values)


def _seed_job(session_factory, storage: LocalStorageAdapter, job_id: str = "job-pipeline") -> None:
    storage.put_bytes(b"fake audio", f"jobs/{job_id}/original/demo.wav", "audio/wav")
    with session_factory() as session:
        audio = AudioFile(
            id=f"audio-{job_id}",
            original_filename="demo.wav",
            content_type="audio/wav",
            file_size_bytes=10,
            duration_seconds=30.0,
            original_storage_key=f"jobs/{job_id}/original/demo.wav",
        )
        job = TranscriptionJob(
            id=job_id,
            audio_file=audio,
            status=JobStatus.QUEUED,
            stage=PipelineStage.QUEUED,
            progress=0,
            title="Demo Song",
        )
        session.add(job)
        session.commit()


def _write_completed_pipeline_output(output_dir: Path, *, include_pdf: bool = True) -> None:
    artifact_paths = {
        "normalized_audio": output_dir / "audio" / "normalized.wav",
        "drums_stem": output_dir / "stems" / "drums.wav",
        "raw_midi": output_dir / "midi" / "raw_drum.mid",
        "processed_midi": output_dir / "midi" / "processed_drum.mid",
        "drum_events": output_dir / "midi" / "drum_events.json",
        "musicxml": output_dir / "notation" / "score.musicxml",
    }
    if include_pdf:
        artifact_paths["pdf"] = output_dir / "exports" / "score.pdf"
    for name, path in artifact_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{name}\n".encode("utf-8"))
    log_payload = {
        "schema_version": "1.0",
        "status": "completed",
        "mock_ai": True,
        "artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "stages": [
            {
                "name": "source_separation",
                "status": "completed",
                "report": {"separator": "mock", "warnings": ["mock_ai_enabled"]},
            },
            {
                "name": "drum_transcription",
                "status": "completed",
                "report": {"transcriber": "mock", "event_count": 5, "warnings": ["mock_ai_enabled"]},
            },
            {
                "name": "midi_post_processing",
                "status": "completed",
                "report": {
                    "output_event_count": 5,
                    "estimated_bpm": 120.0,
                    "time_signature": "4/4",
                    "warnings": [],
                },
            },
            {
                "name": "notation_generation",
                "status": "completed",
                "report": {
                    "event_count": 5,
                    "measure_count": 2,
                    "pdf": {"status": "completed" if include_pdf else "failed", "warnings": []},
                },
            },
        ],
    }
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs" / "pipeline.json").write_text(
        json.dumps(log_payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_failed_pipeline_output(output_dir: Path) -> None:
    log_payload = {
        "schema_version": "1.0",
        "status": "failed",
        "artifacts": {},
        "stages": [
            {
                "name": "drum_transcription",
                "status": "failed",
                "error": {"type": "RuntimeError", "message": "boom"},
            }
        ],
    }
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs" / "pipeline.json").write_text(
        json.dumps(log_payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_pipeline_service_builds_subprocess_command(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        pipeline_adtof_command_template="adtof --audio {input} --out {output}",
        pipeline_adtof_checkpoint_path="/models/adtof.ckpt",
        pipeline_pdf_renderer="/opt/homebrew/bin/mscore",
    )
    runner = PipelineServiceRunner(settings=settings, pipeline_script_path=Path("/repo/scripts/run_local_pipeline.py"))

    command = runner.build_command(
        input_path=Path("/tmp/input.wav"),
        output_dir=Path("/tmp/output"),
        title="Demo",
    )

    assert command == [
        "/opt/groovescribe-ai/bin/python",
        "/repo/scripts/run_local_pipeline.py",
        "--input",
        "/tmp/input.wav",
        "--output-dir",
        "/tmp/output",
        "--title",
        "Demo",
        "--demucs-model-name",
        "htdemucs",
        "--demucs-device",
        "auto",
        "--demucs-timeout-seconds",
        "1800",
        "--adtof-device",
        "cpu",
        "--adtof-threshold",
        "0.5",
        "--adtof-timeout-seconds",
        "1800",
        "--mock-ai",
        "--adtof-command-template",
        "adtof --audio {input} --out {output}",
        "--adtof-checkpoint",
        "/models/adtof.ckpt",
        "--pdf-renderer",
        "/opt/homebrew/bin/mscore",
        "--export-pdf",
    ]


def test_pipeline_service_runs_fake_subprocess_and_writes_metadata(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage)
    calls = []

    def fake_process(command, **_kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_completed_pipeline_output(output_dir)
        return subprocess.CompletedProcess(command, 0, stdout='{"status": "completed"}', stderr="")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        result = runner.run(session, job_id="job-pipeline")
        session.commit()

    assert calls
    assert result.pipeline_log_storage_key == "jobs/job-pipeline/logs/pipeline.json"
    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-pipeline"))
        drum_track = session.scalar(select(DrumTrack).where(DrumTrack.job_id == "job-pipeline"))
        exports = session.scalars(select(ExportFile).where(ExportFile.job_id == "job-pipeline")).all()

        assert job.status == JobStatus.COMPLETED
        assert job.stage == PipelineStage.COMPLETED
        assert job.progress == 100
        assert job.source_separator == "mock"
        assert job.drum_transcriber == "mock"
        assert drum_track.event_count == 5
        assert {export.type for export in exports} == {
            ExportFileType.MIDI,
            ExportFileType.MUSICXML,
            ExportFileType.PDF,
        }
        assert all(export.status == ExportFileStatus.AVAILABLE for export in exports)
        assert storage.exists("jobs/job-pipeline/midi/processed_drum.mid")
        assert storage.exists("jobs/job-pipeline/notation/score.musicxml")
        assert storage.exists("jobs/job-pipeline/exports/score.pdf")


def test_pipeline_service_allows_completed_job_when_optional_pdf_is_missing(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-no-pdf")

    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_completed_pipeline_output(output_dir, include_pdf=False)
        return subprocess.CompletedProcess(command, 0, stdout='{"status": "completed"}', stderr="")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        runner.run(session, job_id="job-no-pdf")
        session.commit()

    with session_factory() as session:
        job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == "job-no-pdf"))
        pdf_export = session.scalar(
            select(ExportFile).where(
                ExportFile.job_id == "job-no-pdf",
                ExportFile.type == ExportFileType.PDF,
            )
        )
        drum_track = session.scalar(select(DrumTrack).where(DrumTrack.job_id == "job-no-pdf"))

        assert job.status == JobStatus.COMPLETED
        assert pdf_export.status == ExportFileStatus.FAILED
        assert pdf_export.error_code == "PDF_EXPORT_FAILED"
        assert "pdf_export_failed" in drum_track.warnings


def test_pipeline_service_maps_failed_stage_to_backend_error(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-failed")

    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_failed_pipeline_output(output_dir)
        return subprocess.CompletedProcess(command, 1, stdout='{"status": "failed"}', stderr="boom")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-failed")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "DRUM_TRANSCRIPTION_FAILED"
            assert exc.error_stage == PipelineStage.DRUM_TRANSCRIPTION.value
            assert exc.internal_error_ref == "jobs/job-failed/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")
