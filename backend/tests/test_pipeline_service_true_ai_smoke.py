from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.models import AudioFile, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.services.pipeline_service import PipelineServiceRunner
from app.services.runtime_diagnostics import RuntimeDiagnosticsService
from app.storage.local import LocalStorageAdapter


@pytest.mark.skipif(
    os.environ.get("RUN_TRUE_AI_SMOKE") != "1",
    reason="set RUN_TRUE_AI_SMOKE=1 to run backend true-AI smoke",
)
def test_pipeline_service_true_ai_smoke_with_synthetic_fixture(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fixture = repo_root / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_clean_drum_pattern.wav"
    adtof_template = os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE")
    if not adtof_template:
        pytest.skip("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE is required for true-AI smoke")
    if not fixture.exists():
        pytest.skip(f"missing fixture: {fixture}")

    diagnostic_settings = Settings(
        pipeline_adtof_command_template=adtof_template,
        pipeline_adtof_verify_input_path=os.environ.get("GROOVESCRIBE_ADTOF_VERIFY_INPUT"),
        pipeline_adtof_verify_output_dir=os.environ.get("GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"),
        pipeline_adtof_device=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"),
        pipeline_adtof_threshold=float(os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", "0.5")),
    )
    preflight = RuntimeDiagnosticsService(settings=diagnostic_settings).get_preflight()
    if preflight.checks.get("adtof", {}).get("status_code") != "ready":
        reason = preflight.checks.get("adtof", {}).get("summary", "ADTOF runtime is not verified")
        pytest.skip(f"ADTOF true-AI smoke requires ready runtime: {reason}")

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'true-ai-smoke.db'}",
        storage_root=str(tmp_path / "storage"),
        pipeline_mock_ai=False,
        pipeline_export_pdf=True,
        pipeline_require_pdf=False,
        pipeline_demucs_device=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"),
        pipeline_adtof_command_template=adtof_template,
        pipeline_adtof_device=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"),
        pipeline_adtof_threshold=float(os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", "0.5")),
        pipeline_adtof_checkpoint_path=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"),
        pipeline_timeout_seconds=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")),
    )
    storage = LocalStorageAdapter(settings.storage_root)
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    job_id = "job-true-ai-smoke"
    storage.put_bytes(fixture.read_bytes(), f"jobs/{job_id}/original/demo.wav", "audio/wav")

    with Session(engine) as session:
        audio = AudioFile(
            id=f"audio-{job_id}",
            original_filename="demo.wav",
            content_type="audio/wav",
            file_size_bytes=fixture.stat().st_size,
            original_storage_key=f"jobs/{job_id}/original/demo.wav",
        )
        job = TranscriptionJob(
            id=job_id,
            audio_file=audio,
            status=JobStatus.QUEUED,
            stage=PipelineStage.QUEUED,
            progress=0,
            title="True AI Smoke",
        )
        session.add(job)
        session.commit()

        PipelineServiceRunner(settings=settings, storage=storage).run(session, job_id=job_id)
        session.commit()

        saved_job = session.scalar(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        exports = session.scalars(select(ExportFile).where(ExportFile.job_id == job_id)).all()

    assert saved_job.status == JobStatus.COMPLETED
    assert storage.exists(f"jobs/{job_id}/logs/pipeline.json")
    assert storage.exists(f"jobs/{job_id}/midi/processed_drum.mid")
    assert storage.exists(f"jobs/{job_id}/notation/score.musicxml")
    assert {
        export.type
        for export in exports
        if export.status == ExportFileStatus.AVAILABLE
    } >= {ExportFileType.MIDI, ExportFileType.MUSICXML}
