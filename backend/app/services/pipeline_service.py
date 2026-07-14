from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode
from app.models import DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import (
    ConfidenceLabel,
    ExportFileStatus,
    ExportFileType,
    JobStatus,
    PipelineStage,
)
from app.services.local_pipeline_runner import LocalPipelineRunResult, LocalPipelineRunnerError
from app.services.pipeline_config import (
    PIPELINE_MODE_DEMO_MOCK,
    PIPELINE_MODE_TRUE_AI,
    pipeline_config_for_job,
)
from app.storage import ArtifactRef, ArtifactType, LocalStorageAdapter, StorageAdapter, build_job_artifact_key
from app.storage.types import CONTENT_TYPE_BY_ARTIFACT_TYPE

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PIPELINE_SCRIPT = _REPO_ROOT / "scripts" / "run_local_pipeline.py"

_PIPELINE_ARTIFACT_TYPES: dict[str, ArtifactType] = {
    "normalized_audio": ArtifactType.NORMALIZED_AUDIO,
    "drums_stem": ArtifactType.DRUMS_STEM,
    "raw_midi": ArtifactType.RAW_MIDI,
    "processed_midi": ArtifactType.PROCESSED_MIDI,
    "performance_midi": ArtifactType.PERFORMANCE_MIDI,
    "drum_events": ArtifactType.DRUM_EVENTS,
    "chart_events": ArtifactType.CHART_EVENTS,
    "visual_preview": ArtifactType.VISUAL_PREVIEW,
    "musicxml": ArtifactType.MUSICXML,
    "pdf": ArtifactType.PDF,
}

_REQUIRED_PIPELINE_ARTIFACTS = (
    "normalized_audio",
    "drums_stem",
    "raw_midi",
    "processed_midi",
    "drum_events",
    "musicxml",
)

_ARTIFACT_TO_BACKEND_STAGE: dict[str, str] = {
    "normalized_audio": PipelineStage.PREPROCESSING.value,
    "drums_stem": PipelineStage.SOURCE_SEPARATION.value,
    "raw_midi": PipelineStage.DRUM_TRANSCRIPTION.value,
    "processed_midi": PipelineStage.MIDI_POST_PROCESSING.value,
    "performance_midi": PipelineStage.NOTATION_GENERATION.value,
    "drum_events": PipelineStage.MIDI_POST_PROCESSING.value,
    "chart_events": PipelineStage.NOTATION_GENERATION.value,
    "visual_preview": PipelineStage.NOTATION_GENERATION.value,
    "musicxml": PipelineStage.NOTATION_GENERATION.value,
    "pdf": PipelineStage.NOTATION_GENERATION.value,
}

_SENSITIVE_KEY_PARTS = (
    "command",
    "template",
    "checkpoint",
    "stderr",
    "stdout",
    "stack",
    "traceback",
    "token",
    "secret",
    "env",
)

_AI_STAGE_TO_BACKEND_STAGE: dict[str, str] = {
    "audio_preprocessing": PipelineStage.PREPROCESSING.value,
    "source_separation": PipelineStage.SOURCE_SEPARATION.value,
    "drum_transcription": PipelineStage.DRUM_TRANSCRIPTION.value,
    "midi_post_processing": PipelineStage.MIDI_POST_PROCESSING.value,
    "notation_generation": PipelineStage.NOTATION_GENERATION.value,
}

_AI_STAGE_TO_ERROR_CODE: dict[str, ErrorCode] = {
    "audio_preprocessing": ErrorCode.AUDIO_DECODE_FAILED,
    "source_separation": ErrorCode.SOURCE_SEPARATION_FAILED,
    "drum_transcription": ErrorCode.DRUM_TRANSCRIPTION_FAILED,
    "midi_post_processing": ErrorCode.MIDI_POST_PROCESSING_FAILED,
    "notation_generation": ErrorCode.NOTATION_GENERATION_FAILED,
}


@dataclass(frozen=True)
class PipelineProcessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class PipelineServiceRunner:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage: StorageAdapter | None = None,
        process_runner: ProcessRunner | None = None,
        pipeline_script_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorageAdapter(self.settings.resolved_storage_root)
        self.process_runner = process_runner or subprocess.run
        self.pipeline_script_path = pipeline_script_path or _PIPELINE_SCRIPT

    def run(
        self,
        db: Session,
        *,
        job_id: str,
        pipeline_config_id: str | None = None,
    ) -> LocalPipelineRunResult:
        job = self._load_job(db, job_id)
        pipeline_config = pipeline_config_for_job(job)
        workspace = self._workspace_path(job.id)
        input_path = self._prepare_input_file(job, workspace)
        output_dir = workspace / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._mark_processing(db, job)
        db.commit()

        command = self.build_command(
            input_path=input_path,
            output_dir=output_dir,
            title=job.title or "GrooveScribe Drum Draft",
            job=job,
        )
        try:
            process = self._run_process(command)
        except LocalPipelineRunnerError as exc:
            log_ref = self._store_pipeline_failure_log(
                job.id,
                output_dir,
                payload={},
                process=None,
                pipeline_config_id=pipeline_config_id,
                pipeline_config=pipeline_config,
                error_code=exc.error_code,
                error_stage=exc.error_stage,
            )
            exc.internal_error_ref = log_ref.storage_key
            raise

        try:
            payload = self._read_pipeline_payload(output_dir, process)
        except json.JSONDecodeError as exc:
            log_ref = self._store_pipeline_failure_log(
                job.id,
                output_dir,
                payload={},
                process=process,
                pipeline_config_id=pipeline_config_id,
                pipeline_config=pipeline_config,
                error_code=ErrorCode.PIPELINE_FAILED.value,
                error_stage=PipelineStage.PREPROCESSING.value,
                failure_reason="invalid_pipeline_json",
            )
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.PIPELINE_FAILED,
                error_stage=PipelineStage.PREPROCESSING.value,
                internal_error_ref=log_ref.storage_key,
            ) from exc

        payload.setdefault("pipeline_config", pipeline_config)
        log_ref = self._store_pipeline_log(job.id, output_dir, payload, process, pipeline_config_id)

        if process.returncode != 0 or payload.get("status") == "failed":
            failed_stage = self._failed_stage(payload)
            raise LocalPipelineRunnerError(
                error_code=_AI_STAGE_TO_ERROR_CODE.get(failed_stage or "", ErrorCode.PIPELINE_FAILED),
                error_stage=_AI_STAGE_TO_BACKEND_STAGE.get(failed_stage or "", job.stage.value),
                internal_error_ref=log_ref.storage_key,
            )

        try:
            artifact_refs = self._store_artifacts(job, payload, output_dir, log_ref.storage_key)
        except LocalPipelineRunnerError as exc:
            exc.internal_error_ref = exc.internal_error_ref or log_ref.storage_key
            self._store_pipeline_failure_log(
                job.id,
                output_dir,
                payload=payload,
                process=process,
                pipeline_config_id=pipeline_config_id,
                pipeline_config=pipeline_config,
                error_code=exc.error_code,
                error_stage=exc.error_stage,
                failure_reason=exc.error_code,
            )
            raise
        self._upsert_metadata(db, job, payload, artifact_refs)
        log_ref = self._store_pipeline_log(
            job.id,
            output_dir,
            payload,
            process,
            pipeline_config_id,
            artifact_storage_keys=self._artifact_storage_keys(artifact_refs),
        )
        self._mark_completed(job, payload, log_ref.storage_key)
        db.flush()
        return LocalPipelineRunResult(job_id=job.id, pipeline_log_storage_key=log_ref.storage_key)

    def build_command(
        self,
        *,
        input_path: Path,
        output_dir: Path,
        title: str,
        job: TranscriptionJob | None = None,
    ) -> list[str]:
        command = [
            self.settings.ai_python_path,
            str(self.pipeline_script_path),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--title",
            title,
            "--demucs-model-name",
            self.settings.pipeline_demucs_model_name,
            "--demucs-device",
            self.settings.pipeline_demucs_device,
            "--demucs-timeout-seconds",
            str(self.settings.pipeline_demucs_timeout_seconds),
            "--adtof-device",
            self.settings.pipeline_adtof_device,
            "--adtof-threshold",
            str(self.settings.pipeline_adtof_threshold),
            "--adtof-timeout-seconds",
            str(self.settings.pipeline_adtof_timeout_seconds),
        ]
        mode = job.pipeline_mode if job and job.pipeline_mode in {PIPELINE_MODE_DEMO_MOCK, PIPELINE_MODE_TRUE_AI} else None
        use_mock = mode == PIPELINE_MODE_DEMO_MOCK if mode else self.settings.pipeline_mock_ai
        if use_mock:
            command.append("--mock-ai")
        if job and mode == PIPELINE_MODE_TRUE_AI:
            if job.adtof_threshold_preset:
                command.extend(["--adtof-threshold-preset", job.adtof_threshold_preset])
            if job.tom_filter_preset:
                command.extend(["--tom-filter-preset", job.tom_filter_preset])
        if self.settings.pipeline_adtof_command_template:
            command.extend(["--adtof-command-template", self.settings.pipeline_adtof_command_template])
        if self.settings.pipeline_adtof_checkpoint_path:
            command.extend(["--adtof-checkpoint", self.settings.pipeline_adtof_checkpoint_path])
        if self.settings.pipeline_performance_gate_calibration_path:
            command.extend(
                ["--performance-gate-calibration", self.settings.pipeline_performance_gate_calibration_path]
            )
        if self.settings.pipeline_pdf_renderer:
            command.extend(["--pdf-renderer", self.settings.pipeline_pdf_renderer])
        if self.settings.pipeline_export_pdf:
            command.append("--export-pdf")
        if self.settings.pipeline_require_pdf:
            command.append("--require-pdf")
        return command

    def _load_job(self, db: Session, job_id: str) -> TranscriptionJob:
        job = (
            db.query(TranscriptionJob)
            .options(
                selectinload(TranscriptionJob.audio_file),
                selectinload(TranscriptionJob.drum_track),
                selectinload(TranscriptionJob.export_files),
            )
            .filter(TranscriptionJob.id == job_id)
            .one_or_none()
        )
        if job is None:
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.JOB_NOT_FOUND,
                error_stage=PipelineStage.QUEUED.value,
            )
        return job

    def _workspace_path(self, job_id: str) -> Path:
        return Path(self.settings.resolved_storage_root) / "jobs" / job_id / "pipeline-work"

    def _prepare_input_file(self, job: TranscriptionJob, workspace: Path) -> Path:
        input_dir = workspace / "input"
        if input_dir.exists():
            shutil.rmtree(input_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        input_path = input_dir / job.audio_file.original_filename
        with self.storage.open_reader(job.audio_file.original_storage_key) as reader:
            input_path.write_bytes(reader.read())
        return input_path

    def _mark_processing(self, db: Session, job: TranscriptionJob) -> None:
        job.status = JobStatus.PROCESSING
        job.stage = PipelineStage.PREPROCESSING
        job.progress = 1
        job.started_at = job.started_at or datetime.now(UTC)
        job.completed_at = None
        job.failed_at = None
        job.error_code = None
        job.error_message = None
        job.error_stage = None
        job.internal_error_ref = None
        db.flush()

    def _run_process(self, command: list[str]) -> PipelineProcessResult:
        try:
            completed = self.process_runner(
                command,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=self.settings.pipeline_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.WORKER_TIMEOUT,
                error_stage=PipelineStage.PREPROCESSING.value,
            ) from exc
        except FileNotFoundError as exc:
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.PIPELINE_FAILED,
                error_stage=PipelineStage.PREPROCESSING.value,
            ) from exc
        return PipelineProcessResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def _read_pipeline_payload(
        self,
        output_dir: Path,
        process: PipelineProcessResult,
    ) -> dict[str, Any]:
        log_path = output_dir / "logs" / "pipeline.json"
        if log_path.exists():
            return json.loads(log_path.read_text(encoding="utf-8"))
        stdout_payload = self._parse_stdout(process.stdout)
        return {
            "schema_version": "1.0",
            "status": "failed" if process.returncode else stdout_payload.get("status", "completed"),
            "artifacts": stdout_payload.get("artifacts", {}),
            "stages": [],
            "subprocess": {
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            },
        }

    def _parse_stdout(self, stdout: str) -> dict[str, Any]:
        if not stdout.strip():
            return {}
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _store_pipeline_log(
        self,
        job_id: str,
        output_dir: Path,
        payload: dict[str, Any],
        process: PipelineProcessResult,
        pipeline_config_id: str | None,
        *,
        artifact_storage_keys: dict[str, str] | None = None,
    ) -> ArtifactRef:
        log_path = self._write_sanitized_pipeline_log(
            output_dir=output_dir,
            payload=payload,
            process=process,
            pipeline_config_id=pipeline_config_id,
            artifact_storage_keys=artifact_storage_keys,
        )
        return self.storage.put_file(
            log_path,
            build_job_artifact_key(job_id, ArtifactType.PIPELINE_LOG),
            CONTENT_TYPE_BY_ARTIFACT_TYPE[ArtifactType.PIPELINE_LOG],
        )

    def _store_pipeline_failure_log(
        self,
        job_id: str,
        output_dir: Path,
        *,
        payload: dict[str, Any],
        process: PipelineProcessResult | None,
        pipeline_config_id: str | None,
        error_code: str,
        error_stage: str,
        pipeline_config: dict | None = None,
        failure_reason: str | None = None,
    ) -> ArtifactRef:
        failure_payload = {
            **payload,
            "status": "failed",
            "runner": "backend.pipeline_service_subprocess",
            "pipeline_config_id": pipeline_config_id,
            "pipeline_config": pipeline_config or payload.get("pipeline_config") or {},
            "error": {
                "code": error_code,
                "stage": error_stage,
                "reason": failure_reason or error_code,
            },
        }
        log_path = self._write_sanitized_pipeline_log(
            output_dir=output_dir,
            payload=failure_payload,
            process=process,
            pipeline_config_id=pipeline_config_id,
        )
        return self.storage.put_file(
            log_path,
            build_job_artifact_key(job_id, ArtifactType.PIPELINE_LOG),
            CONTENT_TYPE_BY_ARTIFACT_TYPE[ArtifactType.PIPELINE_LOG],
        )

    def _write_sanitized_pipeline_log(
        self,
        *,
        output_dir: Path,
        payload: dict[str, Any],
        process: PipelineProcessResult | None,
        pipeline_config_id: str | None,
        artifact_storage_keys: dict[str, str] | None = None,
    ) -> Path:
        log_path = output_dir / "logs" / "pipeline.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        sanitized_payload = self._sanitize_pipeline_payload(
            payload,
            artifact_storage_keys=artifact_storage_keys,
        )
        sanitized_payload["runner"] = "backend.pipeline_service_subprocess"
        sanitized_payload["pipeline_config_id"] = pipeline_config_id
        if process is not None:
            sanitized_payload["subprocess"] = {
                "returncode": process.returncode,
                "executable": Path(process.command[0]).name if process.command else None,
                "script": Path(process.command[1]).name if len(process.command) > 1 else None,
            }
        log_path.write_text(json.dumps(sanitized_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return log_path

    def _store_artifacts(
        self,
        job: TranscriptionJob,
        payload: dict[str, Any],
        output_dir: Path,
        pipeline_log_storage_key: str,
    ) -> dict[ArtifactType, ArtifactRef]:
        artifact_paths = self._artifact_paths(payload, output_dir, pipeline_log_storage_key)
        refs: dict[ArtifactType, ArtifactRef] = {}
        for artifact_name in _REQUIRED_PIPELINE_ARTIFACTS:
            if artifact_name not in artifact_paths:
                raise LocalPipelineRunnerError(
                    error_code=ErrorCode.ARTIFACT_NOT_FOUND,
                    error_stage=_ARTIFACT_TO_BACKEND_STAGE[artifact_name],
                    internal_error_ref=pipeline_log_storage_key,
                )
        for artifact_name, artifact_type in _PIPELINE_ARTIFACT_TYPES.items():
            path = artifact_paths.get(artifact_name)
            if path is None:
                continue
            refs[artifact_type] = self.storage.put_file(
                path,
                build_job_artifact_key(job.id, artifact_type),
                CONTENT_TYPE_BY_ARTIFACT_TYPE[artifact_type],
            )
        return refs

    def _artifact_paths(
        self,
        payload: dict[str, Any],
        output_dir: Path,
        pipeline_log_storage_key: str,
    ) -> dict[str, Path]:
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, dict):
            return {}
        artifact_paths: dict[str, Path] = {}
        for name, value in raw_artifacts.items():
            artifact_name = str(name)
            if artifact_name not in _PIPELINE_ARTIFACT_TYPES:
                continue
            path = self._validated_artifact_path(
                artifact_name=artifact_name,
                raw_value=value,
                output_dir=output_dir,
                pipeline_log_storage_key=pipeline_log_storage_key,
            )
            artifact_paths[artifact_name] = path
        return artifact_paths

    def _validated_artifact_path(
        self,
        *,
        artifact_name: str,
        raw_value: Any,
        output_dir: Path,
        pipeline_log_storage_key: str,
    ) -> Path:
        output_root = output_dir.resolve()
        raw_path = Path(str(raw_value))
        path = raw_path if raw_path.is_absolute() else output_root / raw_path
        resolved = path.resolve()
        error_stage = _ARTIFACT_TO_BACKEND_STAGE[artifact_name]
        if resolved != output_root and output_root not in resolved.parents:
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.ARTIFACT_INVALID,
                error_stage=error_stage,
                internal_error_ref=pipeline_log_storage_key,
            )
        if not path.exists() or not path.is_file():
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.ARTIFACT_NOT_FOUND,
                error_stage=error_stage,
                internal_error_ref=pipeline_log_storage_key,
            )
        if path.stat().st_size == 0:
            raise LocalPipelineRunnerError(
                error_code=ErrorCode.ARTIFACT_INVALID,
                error_stage=error_stage,
                internal_error_ref=pipeline_log_storage_key,
            )
        return resolved

    def _artifact_storage_keys(self, artifact_refs: dict[ArtifactType, ArtifactRef]) -> dict[str, str]:
        keys: dict[str, str] = {}
        for artifact_name, artifact_type in _PIPELINE_ARTIFACT_TYPES.items():
            ref = artifact_refs.get(artifact_type)
            if ref:
                keys[artifact_name] = ref.storage_key
        return keys

    def _sanitize_pipeline_payload(
        self,
        payload: dict[str, Any],
        *,
        artifact_storage_keys: dict[str, str] | None,
    ) -> dict[str, Any]:
        sanitized = self._sanitize_sensitive(payload)
        if not isinstance(sanitized, dict):
            return {}
        sanitized["artifacts"] = artifact_storage_keys or self._sanitized_artifact_placeholders(payload)
        sanitized.pop("input_path", None)
        sanitized.pop("output_dir", None)
        sanitized.pop("log_path", None)
        return sanitized

    def _sanitized_artifact_placeholders(self, payload: dict[str, Any]) -> dict[str, str]:
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, dict):
            return {}
        return {
            str(name): "[redacted]"
            for name in raw_artifacts
            if str(name) in _PIPELINE_ARTIFACT_TYPES
        }

    def _sanitize_sensitive(self, value: Any, *, key: str = "") -> Any:
        if self._is_sensitive_key(key):
            return "[redacted]"
        if isinstance(value, dict):
            return {str(item_key): self._sanitize_sensitive(item, key=str(item_key)) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_sensitive(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_sensitive(item, key=key) for item in value]
        if isinstance(value, str):
            return self._redact_local_text(value)
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = key.lower()
        return any(part in lowered for part in _SENSITIVE_KEY_PARTS)

    def _redact_local_text(self, value: str) -> str:
        redacted = value
        for source, target in (
            (str(_REPO_ROOT), "<repo>"),
            (str(Path.home()), "<home>"),
            (self.settings.ai_python_path, "<ai_python>"),
            (self.settings.resolved_storage_root, "<storage>"),
        ):
            if source:
                redacted = redacted.replace(source, target)
        for prefix in ("/Users/", "/tmp/", "/private/tmp/", "/var/folders/", "/private/var/"):
            if redacted.startswith(prefix):
                return "[redacted]"
        lowered = redacted.lower()
        if "traceback" in lowered or "stack trace" in lowered:
            return "[redacted]"
        return redacted

    def _upsert_metadata(
        self,
        db: Session,
        job: TranscriptionJob,
        payload: dict[str, Any],
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        if ArtifactType.NORMALIZED_AUDIO in artifact_refs:
            job.audio_file.normalized_storage_key = artifact_refs[ArtifactType.NORMALIZED_AUDIO].storage_key
        self._upsert_drum_track(db, job, payload, artifact_refs)
        self._upsert_export_files(db, job, payload, artifact_refs)

    def _upsert_drum_track(
        self,
        db: Session,
        job: TranscriptionJob,
        payload: dict[str, Any],
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        midi_report = self._stage_report(payload, "midi_post_processing")
        transcription_report = self._stage_report(payload, "drum_transcription")
        notation_report = self._stage_report(payload, "notation_generation")
        drum_track = job.drum_track or DrumTrack(job=job)
        drum_track.drums_stem_storage_key = self._storage_key(artifact_refs, ArtifactType.DRUMS_STEM)
        drum_track.raw_midi_storage_key = self._storage_key(artifact_refs, ArtifactType.RAW_MIDI)
        drum_track.processed_midi_storage_key = self._storage_key(artifact_refs, ArtifactType.PROCESSED_MIDI)
        drum_track.drum_events_storage_key = self._storage_key(artifact_refs, ArtifactType.DRUM_EVENTS)
        drum_track.estimated_bpm = self._float_or_none(midi_report.get("estimated_bpm")) or 120.0
        drum_track.time_signature = str(midi_report.get("time_signature") or "4/4")
        drum_track.event_count = self._event_count(midi_report, transcription_report, notation_report)
        drum_track.confidence_label = ConfidenceLabel.MEDIUM if self.settings.pipeline_mock_ai else None
        drum_track.warnings = self._warnings(payload)
        db.add(drum_track)

    def _upsert_export_files(
        self,
        db: Session,
        job: TranscriptionJob,
        payload: dict[str, Any],
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        # Legacy runners only produce processed MIDI. New true-AI runs publish a
        # chart-derived performance MIDI as the user-facing export.
        midi_artifact = (
            ArtifactType.PERFORMANCE_MIDI
            if ArtifactType.PERFORMANCE_MIDI in artifact_refs
            else ArtifactType.PROCESSED_MIDI
        )
        self._upsert_export_file(db, job, ExportFileType.MIDI, midi_artifact, artifact_refs)
        self._upsert_export_file(db, job, ExportFileType.MUSICXML, ArtifactType.MUSICXML, artifact_refs)
        if ArtifactType.PDF in artifact_refs:
            self._upsert_export_file(db, job, ExportFileType.PDF, ArtifactType.PDF, artifact_refs)
        elif self.settings.pipeline_export_pdf:
            self._upsert_failed_pdf_export(db, job, payload)

    def _upsert_export_file(
        self,
        db: Session,
        job: TranscriptionJob,
        export_type: ExportFileType,
        artifact_type: ArtifactType,
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        ref = artifact_refs[artifact_type]
        export = self._find_export(job, export_type)
        if export is None:
            export = ExportFile(job=job, type=export_type)
        export.status = ExportFileStatus.AVAILABLE
        export.storage_key = ref.storage_key
        export.content_type = ref.content_type
        export.file_size_bytes = ref.file_size_bytes
        export.checksum = ref.checksum
        export.error_code = None
        db.add(export)

    def _upsert_failed_pdf_export(
        self,
        db: Session,
        job: TranscriptionJob,
        payload: dict[str, Any],
    ) -> None:
        export = self._find_export(job, ExportFileType.PDF)
        if export is None:
            export = ExportFile(job=job, type=ExportFileType.PDF)
        export.status = ExportFileStatus.FAILED
        export.storage_key = build_job_artifact_key(job.id, ArtifactType.PDF)
        export.content_type = CONTENT_TYPE_BY_ARTIFACT_TYPE[ArtifactType.PDF]
        export.file_size_bytes = None
        export.checksum = None
        export.error_code = self._pdf_error_code(payload)
        db.add(export)

    def _mark_completed(self, job: TranscriptionJob, payload: dict[str, Any], log_storage_key: str) -> None:
        source_report = self._stage_report(payload, "source_separation")
        transcription_report = self._stage_report(payload, "drum_transcription")
        job.status = JobStatus.COMPLETED
        job.stage = PipelineStage.COMPLETED
        job.progress = 100
        job.completed_at = datetime.now(UTC)
        job.failed_at = None
        job.error_code = None
        job.error_message = None
        job.error_stage = None
        job.internal_error_ref = log_storage_key
        job.pipeline_version = "ai-pipeline-local-runner-v1"
        job.source_separator = str(source_report.get("separator") or "")
        job.source_separator_version = str(source_report.get("model_name") or "local-runner")
        job.drum_transcriber = str(transcription_report.get("transcriber") or "")
        job.drum_transcriber_version = str(transcription_report.get("model_name") or "local-runner")

    def _failed_stage(self, payload: dict[str, Any]) -> str | None:
        for stage in self._stages(payload):
            if stage.get("status") == "failed":
                return str(stage.get("name") or stage.get("stage") or "")
        return None

    def _stage_report(self, payload: dict[str, Any], name: str) -> dict[str, Any]:
        for stage in self._stages(payload):
            if stage.get("name") == name or stage.get("stage") == name:
                report = stage.get("report")
                return report if isinstance(report, dict) else {}
        return {}

    def _stages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_stages = payload.get("stages") or payload.get("stage_reports") or []
        if not isinstance(raw_stages, list):
            return []
        return [stage for stage in raw_stages if isinstance(stage, dict)]

    def _warnings(self, payload: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for stage in self._stages(payload):
            report = stage.get("report")
            if not isinstance(report, dict):
                continue
            raw_warnings = report.get("warnings")
            if isinstance(raw_warnings, list):
                warnings.extend(str(warning) for warning in raw_warnings)
            pdf_report = report.get("pdf")
            if isinstance(pdf_report, dict):
                pdf_warnings = pdf_report.get("warnings")
                if isinstance(pdf_warnings, list):
                    warnings.extend(str(warning) for warning in pdf_warnings)
                if pdf_report.get("status") == "failed":
                    warnings.append("pdf_export_failed")
        return list(dict.fromkeys(warnings))

    def _event_count(
        self,
        midi_report: dict[str, Any],
        transcription_report: dict[str, Any],
        notation_report: dict[str, Any],
    ) -> int:
        for key, report in (
            ("output_event_count", midi_report),
            ("event_count", transcription_report),
            ("event_count", notation_report),
        ):
            value = report.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return 0

    def _pdf_error_code(self, payload: dict[str, Any]) -> str | None:
        pdf_report = self._stage_report(payload, "notation_generation").get("pdf")
        if isinstance(pdf_report, dict) and pdf_report.get("status") == "failed":
            return ErrorCode.PDF_EXPORT_FAILED.value
        return None

    def _find_export(self, job: TranscriptionJob, export_type: ExportFileType) -> ExportFile | None:
        return next((export for export in job.export_files if export.type == export_type), None)

    def _storage_key(
        self,
        artifact_refs: dict[ArtifactType, ArtifactRef],
        artifact_type: ArtifactType,
    ) -> str | None:
        ref = artifact_refs.get(artifact_type)
        return ref.storage_key if ref else None

    def _float_or_none(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
