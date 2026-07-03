from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

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
from app.storage import (
    ArtifactRef,
    ArtifactType,
    LocalStorageAdapter,
    StorageAdapter,
    build_job_artifact_key,
)
from app.storage.types import CONTENT_TYPE_BY_ARTIFACT_TYPE


@dataclass(frozen=True)
class LocalPipelineRunResult:
    job_id: str
    pipeline_log_storage_key: str


class LocalMockPipelineRunner:
    """Backend-owned mock runner used by the local-first V1 queue slice."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage: StorageAdapter | None = None,
        fail_stage: PipelineStage | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorageAdapter(self.settings.storage_root)
        self.fail_stage = fail_stage

    def run(
        self,
        db: Session,
        *,
        job_id: str,
        pipeline_config_id: str | None = None,
    ) -> LocalPipelineRunResult:
        job = self._load_job(db, job_id)
        started_at = datetime.now(UTC)
        stage_reports: list[dict[str, object]] = []
        artifact_refs: dict[ArtifactType, ArtifactRef] = {}

        job.status = JobStatus.PROCESSING
        job.stage = PipelineStage.PREPROCESSING
        job.progress = 1
        job.started_at = job.started_at or started_at
        job.error_code = None
        job.error_message = None
        job.error_stage = None
        job.internal_error_ref = None
        db.flush()

        for stage, progress in (
            (PipelineStage.PREPROCESSING, 10),
            (PipelineStage.SOURCE_SEPARATION, 25),
            (PipelineStage.STEM_VALIDATION, 45),
            (PipelineStage.DRUM_TRANSCRIPTION, 60),
            (PipelineStage.MIDI_POST_PROCESSING, 75),
            (PipelineStage.NOTATION_GENERATION, 88),
            (PipelineStage.PDF_EXPORT, 95),
        ):
            if self.fail_stage == stage:
                log_key = self._write_pipeline_log(
                    job_id=job.id,
                    status="failed",
                    pipeline_config_id=pipeline_config_id,
                    stage_reports=[
                        *stage_reports,
                        self._stage_report(stage=stage, status="failed", progress=progress),
                    ],
                    artifact_refs=artifact_refs,
                )
                raise LocalPipelineRunnerError(
                    error_code=self._error_code_for_stage(stage),
                    error_stage=stage.value,
                    internal_error_ref=log_key,
                )

            job.stage = stage
            job.progress = progress
            artifact_refs.update(self._write_stage_artifacts(job, stage))
            stage_reports.append(self._stage_report(stage=stage, status="completed", progress=progress))
            db.flush()

        self._upsert_drum_track(db, job, artifact_refs)
        self._upsert_export_files(db, job, artifact_refs)

        job.status = JobStatus.COMPLETED
        job.stage = PipelineStage.COMPLETED
        job.progress = 100
        job.completed_at = datetime.now(UTC)
        job.failed_at = None
        job.pipeline_version = "local-mock-v1"
        job.source_separator = "mock"
        job.source_separator_version = "local-v1"
        job.drum_transcriber = "mock"
        job.drum_transcriber_version = "local-v1"

        log_key = self._write_pipeline_log(
            job_id=job.id,
            status="completed",
            pipeline_config_id=pipeline_config_id,
            stage_reports=[
                *stage_reports,
                self._stage_report(stage=PipelineStage.COMPLETED, status="completed", progress=100),
            ],
            artifact_refs=artifact_refs,
        )
        job.internal_error_ref = log_key
        db.flush()
        return LocalPipelineRunResult(job_id=job.id, pipeline_log_storage_key=log_key)

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

    def _write_stage_artifacts(
        self,
        job: TranscriptionJob,
        stage: PipelineStage,
    ) -> dict[ArtifactType, ArtifactRef]:
        if stage == PipelineStage.PREPROCESSING:
            ref = self._put_text(job.id, ArtifactType.NORMALIZED_AUDIO, "normalized mock wav\n")
            job.audio_file.normalized_storage_key = ref.storage_key
            return {ArtifactType.NORMALIZED_AUDIO: ref}
        if stage == PipelineStage.SOURCE_SEPARATION:
            return {ArtifactType.DRUMS_STEM: self._put_text(job.id, ArtifactType.DRUMS_STEM, "mock drums stem\n")}
        if stage == PipelineStage.DRUM_TRANSCRIPTION:
            events = {
                "schema_version": "1.0",
                "events": [
                    {"time": 0.0, "instrument": "kick", "velocity": 100},
                    {"time": 0.5, "instrument": "snare", "velocity": 92},
                    {"time": 1.0, "instrument": "closed_hihat", "velocity": 70},
                    {"time": 1.5, "instrument": "snare", "velocity": 88},
                ],
            }
            return {
                ArtifactType.RAW_MIDI: self._put_bytes(job.id, ArtifactType.RAW_MIDI, b"MThd mock raw midi\n"),
                ArtifactType.DRUM_EVENTS: self._put_json(job.id, ArtifactType.DRUM_EVENTS, events),
            }
        if stage == PipelineStage.MIDI_POST_PROCESSING:
            return {
                ArtifactType.PROCESSED_MIDI: self._put_bytes(
                    job.id,
                    ArtifactType.PROCESSED_MIDI,
                    b"MThd mock processed midi\n",
                )
            }
        if stage == PipelineStage.NOTATION_GENERATION:
            return {
                ArtifactType.MUSICXML: self._put_text(
                    job.id,
                    ArtifactType.MUSICXML,
                    '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0"></score-partwise>\n',
                )
            }
        if stage == PipelineStage.PDF_EXPORT:
            return {ArtifactType.PDF: self._put_bytes(job.id, ArtifactType.PDF, b"%PDF-1.4\n% mock score\n")}
        return {}

    def _upsert_drum_track(
        self,
        db: Session,
        job: TranscriptionJob,
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        drum_track = job.drum_track or DrumTrack(job=job)
        drum_track.drums_stem_storage_key = self._storage_key(artifact_refs, ArtifactType.DRUMS_STEM)
        drum_track.raw_midi_storage_key = self._storage_key(artifact_refs, ArtifactType.RAW_MIDI)
        drum_track.processed_midi_storage_key = self._storage_key(artifact_refs, ArtifactType.PROCESSED_MIDI)
        drum_track.drum_events_storage_key = self._storage_key(artifact_refs, ArtifactType.DRUM_EVENTS)
        drum_track.estimated_bpm = 120.0
        drum_track.time_signature = "4/4"
        drum_track.event_count = 4
        drum_track.confidence_label = ConfidenceLabel.MEDIUM
        drum_track.warnings = ["local mock runner output; replace with AI pipeline in a later V1 slice"]
        db.add(drum_track)

    def _upsert_export_files(
        self,
        db: Session,
        job: TranscriptionJob,
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> None:
        for export_type, artifact_type in (
            (ExportFileType.MIDI, ArtifactType.PROCESSED_MIDI),
            (ExportFileType.MUSICXML, ArtifactType.MUSICXML),
            (ExportFileType.PDF, ArtifactType.PDF),
        ):
            ref = artifact_refs[artifact_type]
            export = next((item for item in job.export_files if item.type == export_type), None)
            if export is None:
                export = ExportFile(job=job, type=export_type)
            export.status = ExportFileStatus.AVAILABLE
            export.storage_key = ref.storage_key
            export.content_type = ref.content_type
            export.file_size_bytes = ref.file_size_bytes
            export.checksum = ref.checksum
            export.error_code = None
            db.add(export)

    def _write_pipeline_log(
        self,
        *,
        job_id: str,
        status: str,
        pipeline_config_id: str | None,
        stage_reports: list[dict[str, object]],
        artifact_refs: dict[ArtifactType, ArtifactRef],
    ) -> str:
        payload = {
            "schema_version": "1.0",
            "runner": "backend.local_mock_pipeline_runner",
            "job_id": job_id,
            "status": status,
            "pipeline_config_id": pipeline_config_id,
            "created_at": datetime.now(UTC).isoformat(),
            "artifacts": {
                artifact_type.value: ref.storage_key for artifact_type, ref in sorted(artifact_refs.items())
            },
            "stage_reports": stage_reports,
            "quality": self._quality_summary(artifact_refs),
        }
        return self._put_json(job_id, ArtifactType.PIPELINE_LOG, payload).storage_key

    def _stage_report(self, *, stage: PipelineStage, status: str, progress: int) -> dict[str, object]:
        return {
            "stage": stage.value,
            "status": status,
            "progress": progress,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _quality_summary(self, artifact_refs: dict[ArtifactType, ArtifactRef]) -> dict[str, object] | None:
        if ArtifactType.PROCESSED_MIDI not in artifact_refs:
            return None
        return {
            "schema_version": "1.0",
            "raw_event_count": 4,
            "processed_event_count": 4,
            "raw_note_histogram": {"36": 1, "38": 2, "42": 1},
            "processed_drum_counts": {"closed_hat": 1, "kick": 1, "snare": 2},
            "duration_seconds": 1.5,
            "tempo_bpm": 120.0,
            "estimated_measure_count": 1,
            "quality_flags": ["sparse_transcription"],
            "warnings": ["sparse_transcription"],
        }

    def _put_text(self, job_id: str, artifact_type: ArtifactType, content: str) -> ArtifactRef:
        return self._put_bytes(job_id, artifact_type, content.encode("utf-8"))

    def _put_json(self, job_id: str, artifact_type: ArtifactType, payload: dict[str, object]) -> ArtifactRef:
        return self._put_bytes(job_id, artifact_type, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    def _put_bytes(self, job_id: str, artifact_type: ArtifactType, content: bytes) -> ArtifactRef:
        return self.storage.put_bytes(
            content,
            build_job_artifact_key(job_id, artifact_type),
            CONTENT_TYPE_BY_ARTIFACT_TYPE[artifact_type],
        )

    def _storage_key(
        self,
        artifact_refs: dict[ArtifactType, ArtifactRef],
        artifact_type: ArtifactType,
    ) -> str | None:
        ref = artifact_refs.get(artifact_type)
        return ref.storage_key if ref else None

    def _error_code_for_stage(self, stage: PipelineStage) -> ErrorCode:
        return {
            PipelineStage.SOURCE_SEPARATION: ErrorCode.SOURCE_SEPARATION_FAILED,
            PipelineStage.DRUM_TRANSCRIPTION: ErrorCode.DRUM_TRANSCRIPTION_FAILED,
            PipelineStage.MIDI_POST_PROCESSING: ErrorCode.MIDI_POST_PROCESSING_FAILED,
            PipelineStage.NOTATION_GENERATION: ErrorCode.NOTATION_GENERATION_FAILED,
            PipelineStage.PDF_EXPORT: ErrorCode.PDF_EXPORT_FAILED,
        }.get(stage, ErrorCode.PIPELINE_FAILED)


class LocalPipelineRunnerError(Exception):
    def __init__(
        self,
        *,
        error_code: str | ErrorCode,
        error_stage: str,
        internal_error_ref: str | None = None,
    ) -> None:
        self.error_code = str(error_code.value if isinstance(error_code, ErrorCode) else error_code)
        self.error_stage = error_stage
        self.internal_error_ref = internal_error_ref
        super().__init__(self.error_code)
