from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob, User
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage


def test_models_can_be_created_and_queried() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="dev@example.com", display_name="Dev")
        audio = AudioFile(
            user=user,
            original_filename="sample.wav",
            content_type="audio/wav",
            file_size_bytes=1024,
            original_storage_key="jobs/job-1/original/sample.wav",
        )
        job = TranscriptionJob(
            user=user,
            audio_file=audio,
            status=JobStatus.QUEUED,
            stage=PipelineStage.QUEUED,
            title="Sample",
        )
        drum_track = DrumTrack(
            job=job,
            processed_midi_storage_key="jobs/job-1/midi/processed_drum.mid",
            drum_events_storage_key="jobs/job-1/midi/drum_events.json",
            event_count=4,
            warnings=["mock_ai_enabled"],
        )
        export = ExportFile(
            job=job,
            type=ExportFileType.MIDI,
            status=ExportFileStatus.AVAILABLE,
            storage_key="jobs/job-1/midi/processed_drum.mid",
            content_type="audio/midi",
        )
        session.add_all([user, audio, job, drum_track, export])
        session.commit()

        saved_job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.title == "Sample"))
        assert saved_job is not None
        assert saved_job.status == JobStatus.QUEUED
        assert saved_job.stage == PipelineStage.QUEUED
        assert saved_job.audio_file.original_filename == "sample.wav"
        assert saved_job.drum_track.event_count == 4
        assert saved_job.export_files[0].type == ExportFileType.MIDI


def test_enum_values_match_level_1_contract() -> None:
    assert [status.value for status in JobStatus] == [
        "uploaded",
        "queued",
        "processing",
        "completed",
        "failed",
        "interrupted",
        "canceled",
    ]
    assert PipelineStage.MIDI_POST_PROCESSING.value == "midi_post_processing"
    assert ExportFileType.MUSICXML.value == "musicxml"
    assert ExportFileStatus.AVAILABLE.value == "available"


def test_source_job_id_is_logical_reference_without_db_foreign_key() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("transcription_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("transcription_jobs")}
    foreign_keys = inspector.get_foreign_keys("transcription_jobs")

    assert "source_job_id" in columns
    assert "ix_transcription_jobs_source_job_id" in indexes
    assert not any("source_job_id" in foreign_key.get("constrained_columns", []) for foreign_key in foreign_keys)
