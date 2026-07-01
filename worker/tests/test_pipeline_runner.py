from __future__ import annotations

import json

from sqlalchemy import select

from app.config import WorkerSettings
from app.constants import ExportFileStatus, JobStatus, PipelineStage
from app.db import audio_files, drum_tracks, export_files, transcription_jobs
from app.error_handling import PipelineStageError
from app.pipeline_runner import MockPipelineRunner
from app.storage import LocalWorkerStorage

from helpers import seed_queued_job, session_factory


def test_mock_pipeline_runner_completes_job_and_writes_metadata(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(database_url="sqlite+pysqlite:///:memory:", storage_root=str(tmp_path / "storage"))
    runner = MockPipelineRunner(settings=settings, storage=LocalWorkerStorage(settings.storage_root))

    with factory() as session:
        seed_queued_job(session)
        result = runner.run(session=session, job_id="job-1")
        session.commit()

        job = session.execute(select(transcription_jobs).where(transcription_jobs.c.id == "job-1")).mappings().one()
        audio = session.execute(select(audio_files).where(audio_files.c.id == "audio-job-1")).mappings().one()
        track = session.execute(select(drum_tracks).where(drum_tracks.c.job_id == "job-1")).mappings().one()
        exports = session.execute(select(export_files).where(export_files.c.job_id == "job-1")).mappings().all()

        assert job["status"] == JobStatus.COMPLETED.value
        assert job["stage"] == PipelineStage.COMPLETED.value
        assert audio["normalized_storage_key"] == "jobs/job-1/audio/normalized.wav"
        assert track["drums_stem_storage_key"] == "jobs/job-1/stems/drums.wav"
        assert track["raw_midi_storage_key"] == "jobs/job-1/midi/raw_drum.mid"
        assert track["processed_midi_storage_key"] == "jobs/job-1/midi/processed_drum.mid"
        assert track["drum_events_storage_key"] == "jobs/job-1/midi/drum_events.json"
        assert {export["type"] for export in exports} == {"midi", "musicxml", "pdf"}
        assert {export["status"] for export in exports} == {ExportFileStatus.AVAILABLE.value}
        assert result.artifact_keys["normalized_audio"] == "jobs/job-1/audio/normalized.wav"
        assert result.artifact_keys["drums_stem"] == "jobs/job-1/stems/drums.wav"
        assert result.artifact_keys["raw_midi"] == "jobs/job-1/midi/raw_drum.mid"
        assert result.artifact_keys["processed_midi"] == "jobs/job-1/midi/processed_drum.mid"
        assert result.artifact_keys["drum_events"] == "jobs/job-1/midi/drum_events.json"
        assert result.artifact_keys["musicxml"] == "jobs/job-1/notation/score.musicxml"
        assert result.artifact_keys["pdf"] == "jobs/job-1/exports/score.pdf"
        assert result.log_storage_key == "jobs/job-1/logs/pipeline.json"
        log_path = tmp_path / "storage/jobs/job-1/logs/pipeline.json"
        assert log_path.is_file()
        log_payload = json.loads(log_path.read_text(encoding="utf-8"))
        assert [report["name"] for report in log_payload["stage_reports"]] == [
            PipelineStage.PREPROCESSING.value,
            PipelineStage.SOURCE_SEPARATION.value,
            PipelineStage.STEM_VALIDATION.value,
            PipelineStage.DRUM_TRANSCRIPTION.value,
            PipelineStage.MIDI_POST_PROCESSING.value,
            PipelineStage.NOTATION_GENERATION.value,
            PipelineStage.PDF_EXPORT.value,
        ]
        assert log_payload["stage_reports"][-1]["status"] == "completed_with_warning"
        assert log_payload["stage_reports"][-1]["report"]["pdf"]["warnings"] == ["mock_pdf_completed_with_warning"]
        assert (tmp_path / "storage/jobs/job-1/midi/drum_events.json").is_file()


def test_mock_pipeline_runner_failure_preserves_stage_for_task_boundary(tmp_path) -> None:
    factory = session_factory(tmp_path)
    settings = WorkerSettings(database_url="sqlite+pysqlite:///:memory:", storage_root=str(tmp_path / "storage"))
    runner = MockPipelineRunner(
        settings=settings,
        storage=LocalWorkerStorage(settings.storage_root),
        fail_stage=PipelineStage.DRUM_TRANSCRIPTION.value,
    )

    with factory() as session:
        seed_queued_job(session)
        try:
            runner.run(session=session, job_id="job-1")
        except PipelineStageError as exc:
            assert exc.stage == PipelineStage.DRUM_TRANSCRIPTION.value
            assert session.execute(
                select(transcription_jobs.c.stage).where(transcription_jobs.c.id == "job-1")
            ).scalar_one() == PipelineStage.DRUM_TRANSCRIPTION.value
            log_payload = json.loads((tmp_path / "storage/jobs/job-1/logs/pipeline.json").read_text(encoding="utf-8"))
            assert log_payload["stage_reports"][-1]["name"] == PipelineStage.DRUM_TRANSCRIPTION.value
            assert log_payload["stage_reports"][-1]["status"] == "failed"
            assert log_payload["stage_reports"][-1]["error"]["stage"] == PipelineStage.DRUM_TRANSCRIPTION.value
        else:
            raise AssertionError("expected PipelineStageError")
