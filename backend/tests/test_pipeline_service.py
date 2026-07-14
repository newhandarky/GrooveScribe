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


def _seed_job(
    session_factory,
    storage: LocalStorageAdapter,
    job_id: str = "job-pipeline",
    *,
    pipeline_mode: str | None = None,
    adtof_threshold_preset: str | None = None,
    tom_filter_preset: str | None = None,
    runtime_fallback_status: str | None = None,
) -> None:
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
            pipeline_mode=pipeline_mode,
            adtof_threshold_preset=adtof_threshold_preset,
            tom_filter_preset=tom_filter_preset,
            runtime_fallback_status=runtime_fallback_status,
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
        "chart_events": output_dir / "notation" / "chart_events.json",
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


def _read_storage_json(storage: LocalStorageAdapter, storage_key: str) -> dict:
    with storage.open_reader(storage_key) as reader:
        return json.loads(reader.read().decode("utf-8"))


def test_pipeline_service_builds_subprocess_command(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        pipeline_adtof_command_template="adtof --audio {input} --out {output}",
        pipeline_adtof_checkpoint_path="/models/adtof.ckpt",
        pipeline_performance_gate_calibration_path="/private/calibration/gate_calibration.json",
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
        "--performance-gate-calibration",
        "/private/calibration/gate_calibration.json",
        "--pdf-renderer",
        "/opt/homebrew/bin/mscore",
        "--export-pdf",
    ]


def test_pipeline_service_builds_true_ai_command_from_job_config(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runner = PipelineServiceRunner(settings=settings, pipeline_script_path=Path("/repo/scripts/run_local_pipeline.py"))
    job = TranscriptionJob(
        id="job-true-ai",
        pipeline_mode="true_ai",
        adtof_threshold_preset="separated_v1",
        tom_filter_preset="tom_guard_v1",
    )

    command = runner.build_command(
        input_path=Path("/tmp/input.wav"),
        output_dir=Path("/tmp/output"),
        title="Demo",
        job=job,
    )

    assert "--mock-ai" not in command
    assert command[command.index("--adtof-threshold-preset") + 1] == "separated_v1"
    assert command[command.index("--tom-filter-preset") + 1] == "tom_guard_v1"


def test_pipeline_service_passes_private_calibration_only_to_subprocess(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        pipeline_performance_gate_calibration_path="/private/calibration/gate_calibration.json",
    )
    runner = PipelineServiceRunner(settings=settings, pipeline_script_path=Path("/repo/scripts/run_local_pipeline.py"))

    command = runner.build_command(
        input_path=Path("/tmp/input.wav"),
        output_dir=Path("/tmp/output"),
        title="Demo",
        job=TranscriptionJob(id="job-true-ai", pipeline_mode="true_ai"),
    )

    assert command[command.index("--performance-gate-calibration") + 1] == "/private/calibration/gate_calibration.json"


def test_pipeline_service_builds_demo_mock_command_from_job_config(tmp_path: Path) -> None:
    settings = _settings(tmp_path, pipeline_mock_ai=False)
    runner = PipelineServiceRunner(settings=settings, pipeline_script_path=Path("/repo/scripts/run_local_pipeline.py"))
    job = TranscriptionJob(id="job-demo", pipeline_mode="demo_mock")

    command = runner.build_command(
        input_path=Path("/tmp/input.wav"),
        output_dir=Path("/tmp/output"),
        title="Demo",
        job=job,
    )

    assert "--mock-ai" in command
    assert "--adtof-threshold-preset" not in command
    assert "--tom-filter-preset" not in command


def test_pipeline_service_treats_unknown_job_config_as_global_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path, pipeline_mock_ai=True)
    runner = PipelineServiceRunner(settings=settings, pipeline_script_path=Path("/repo/scripts/run_local_pipeline.py"))
    job = TranscriptionJob(id="job-legacy", pipeline_mode="unknown")

    command = runner.build_command(
        input_path=Path("/tmp/input.wav"),
        output_dir=Path("/tmp/output"),
        title="Demo",
        job=job,
    )

    assert "--mock-ai" in command
    assert "--adtof-threshold-preset" not in command
    assert "--tom-filter-preset" not in command


def test_pipeline_service_runs_fake_subprocess_and_writes_metadata(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(
        session_factory,
        storage,
        pipeline_mode="true_ai",
        adtof_threshold_preset="separated_v1",
        tom_filter_preset="tom_guard_v1",
        runtime_fallback_status="not_applied",
    )
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
        log_payload = _read_storage_json(storage, "jobs/job-pipeline/logs/pipeline.json")
        assert log_payload["artifacts"]["musicxml"] == "jobs/job-pipeline/notation/score.musicxml"
        assert log_payload["pipeline_config"] == {
            "mode": "true_ai",
            "adtof_threshold_preset": "separated_v1",
            "tom_filter_preset": "tom_guard_v1",
            "runtime_fallback_status": "not_applied",
            "source_job_id": None,
        }
        assert str(tmp_path) not in json.dumps(log_payload)


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


def test_pipeline_service_rejects_artifact_path_outside_workspace(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-outside")
    outside_musicxml = tmp_path / "outside.musicxml"
    outside_musicxml.write_text("<score-partwise />", encoding="utf-8")

    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_completed_pipeline_output(output_dir)
        log_path = output_dir / "logs" / "pipeline.json"
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        payload["artifacts"]["musicxml"] = str(outside_musicxml)
        log_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"status": "completed"}', stderr="")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-outside")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "ARTIFACT_INVALID"
            assert exc.error_stage == PipelineStage.NOTATION_GENERATION.value
            assert exc.internal_error_ref == "jobs/job-outside/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")

    log_payload = _read_storage_json(storage, "jobs/job-outside/logs/pipeline.json")
    assert log_payload["error"]["code"] == "ARTIFACT_INVALID"
    assert str(outside_musicxml) not in json.dumps(log_payload)


def test_pipeline_service_maps_missing_required_artifact_to_producer_stage(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-missing-musicxml")

    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_completed_pipeline_output(output_dir)
        log_path = output_dir / "logs" / "pipeline.json"
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        del payload["artifacts"]["musicxml"]
        log_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"status": "completed"}', stderr="")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-missing-musicxml")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "ARTIFACT_NOT_FOUND"
            assert exc.error_stage == PipelineStage.NOTATION_GENERATION.value
            assert exc.internal_error_ref == "jobs/job-missing-musicxml/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")


def test_pipeline_service_writes_failure_log_for_timeout(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-timeout")

    def fake_process(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, timeout=123)

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-timeout")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "WORKER_TIMEOUT"
            assert exc.internal_error_ref == "jobs/job-timeout/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")

    log_payload = _read_storage_json(storage, "jobs/job-timeout/logs/pipeline.json")
    encoded = json.dumps(log_payload)
    assert log_payload["error"]["code"] == "WORKER_TIMEOUT"
    assert "stdout" not in encoded
    assert "stderr" not in encoded
    assert str(tmp_path) not in encoded


def test_pipeline_service_writes_failure_log_for_missing_ai_python(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-missing-python")

    def fake_process(*_args, **_kwargs):
        raise FileNotFoundError("python missing")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-missing-python")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "PIPELINE_FAILED"
            assert exc.internal_error_ref == "jobs/job-missing-python/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")

    log_payload = _read_storage_json(storage, "jobs/job-missing-python/logs/pipeline.json")
    assert log_payload["error"]["code"] == "PIPELINE_FAILED"


def test_pipeline_service_writes_failure_log_for_invalid_pipeline_json(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _settings(tmp_path)
    storage = LocalStorageAdapter(settings.storage_root)
    _seed_job(session_factory, storage, "job-invalid-json")

    def fake_process(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "logs").mkdir(parents=True, exist_ok=True)
        (output_dir / "logs" / "pipeline.json").write_text("{not-json", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="Traceback at /tmp/private")

    runner = PipelineServiceRunner(settings=settings, storage=storage, process_runner=fake_process)

    with session_factory() as session:
        try:
            runner.run(session, job_id="job-invalid-json")
        except LocalPipelineRunnerError as exc:
            assert exc.error_code == "PIPELINE_FAILED"
            assert exc.internal_error_ref == "jobs/job-invalid-json/logs/pipeline.json"
        else:
            raise AssertionError("expected LocalPipelineRunnerError")

    log_payload = _read_storage_json(storage, "jobs/job-invalid-json/logs/pipeline.json")
    encoded = json.dumps(log_payload)
    assert log_payload["error"]["reason"] == "invalid_pipeline_json"
    assert "Traceback" not in encoded
    assert "/tmp/private" not in encoded
