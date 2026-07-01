from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from .config import WorkerSettings, get_worker_settings
from .constants import ConfidenceLabel, ExportFileStatus, ExportFileType, PipelineStage
from .db import audio_files, drum_tracks, export_files, transcription_jobs
from .error_handling import PipelineStageError
from .logging import PipelineLog
from .services.job_status_service import JobStatusService
from .storage import LocalWorkerStorage, StoredArtifact, job_artifact_key


STAGE_PROGRESS: tuple[tuple[PipelineStage, int], ...] = (
    (PipelineStage.PREPROCESSING, 10),
    (PipelineStage.SOURCE_SEPARATION, 25),
    (PipelineStage.STEM_VALIDATION, 45),
    (PipelineStage.DRUM_TRANSCRIPTION, 60),
    (PipelineStage.MIDI_POST_PROCESSING, 75),
    (PipelineStage.NOTATION_GENERATION, 88),
    (PipelineStage.PDF_EXPORT, 95),
)


@dataclass(frozen=True)
class PipelineResult:
    job_id: str
    artifact_keys: dict[str, str]
    log_storage_key: str


@dataclass(frozen=True)
class JobInput:
    job_id: str
    audio_file_id: str
    original_storage_key: str


class MockPipelineRunner:
    def __init__(
        self,
        *,
        settings: WorkerSettings | None = None,
        storage: LocalWorkerStorage | None = None,
        fail_stage: str | None = None,
    ) -> None:
        self.settings = settings or get_worker_settings()
        self.storage = storage or LocalWorkerStorage(self.settings.storage_root)
        self.fail_stage = fail_stage

    def run(self, *, session: Session, job_id: str, pipeline_config_id: str | None = None) -> PipelineResult:
        job_input = self._load_job_input(session, job_id)
        status = JobStatusService(session)
        pipeline_log = PipelineLog(job_id=job_id)
        artifact_keys: dict[str, str] = {"original_audio": job_input.original_storage_key}

        status.mark_processing(job_id)
        pipeline_log.add("job_started", stage=PipelineStage.PREPROCESSING.value, pipeline_config_id=pipeline_config_id)

        try:
            for stage, progress in STAGE_PROGRESS:
                status.update_stage(job_id, stage.value, progress)
                timer = None
                try:
                    with pipeline_log.time_stage(stage.value) as timer:
                        self._maybe_fail(stage.value)
                        stage_artifacts = self._write_stage_artifacts(session, job_id, stage)
                except Exception as exc:
                    pipeline_log.add_stage_report(
                        name=stage.value,
                        status="failed",
                        runtime_seconds=timer.runtime_seconds if timer else None,
                        error=self._serialize_stage_error(exc, stage.value),
                    )
                    raise
                artifact_keys.update(stage_artifacts)
                pipeline_log.add_stage_report(
                    name=stage.value,
                    status=self._mock_stage_status(stage),
                    runtime_seconds=timer.runtime_seconds if timer else None,
                    artifacts=stage_artifacts,
                    report=self._mock_stage_report(stage),
                )
            self._write_mock_metadata(session, job_id, artifact_keys)
            log_ref = self._write_pipeline_log(job_id, pipeline_log)
            status.mark_completed(job_id)
            session.execute(
                update(transcription_jobs)
                .where(transcription_jobs.c.id == job_id)
                .values(
                    pipeline_version=self.settings.pipeline_version,
                    source_separator="mock",
                    source_separator_version="phase3",
                    drum_transcriber="mock",
                    drum_transcriber_version="phase3",
                )
            )
            return PipelineResult(job_id=job_id, artifact_keys=artifact_keys, log_storage_key=log_ref.storage_key)
        except Exception:
            self._write_pipeline_log(job_id, pipeline_log)
            raise

    def _load_job_input(self, session: Session, job_id: str) -> JobInput:
        row = session.execute(
            select(
                transcription_jobs.c.id,
                transcription_jobs.c.audio_file_id,
                audio_files.c.original_storage_key,
            )
            .join(audio_files, audio_files.c.id == transcription_jobs.c.audio_file_id)
            .where(transcription_jobs.c.id == job_id)
        ).mappings().one_or_none()
        if row is None:
            from .services.job_status_service import JobNotFoundError

            raise JobNotFoundError(job_id)
        return JobInput(
            job_id=row["id"],
            audio_file_id=row["audio_file_id"],
            original_storage_key=row["original_storage_key"],
        )

    def _write_stage_artifacts(self, session: Session, job_id: str, stage: PipelineStage) -> dict[str, str]:
        if stage == PipelineStage.PREPROCESSING:
            artifact = self._put(job_id, "audio/normalized.wav", b"mock normalized audio\n", "audio/wav")
            session.execute(
                update(audio_files)
                .where(audio_files.c.id == select(transcription_jobs.c.audio_file_id).where(transcription_jobs.c.id == job_id).scalar_subquery())
                .values(normalized_storage_key=artifact.storage_key)
            )
            return {"normalized_audio": artifact.storage_key}
        if stage == PipelineStage.SOURCE_SEPARATION:
            artifact = self._put(job_id, "stems/drums.wav", b"mock drums stem\n", "audio/wav")
            return {"drums_stem": artifact.storage_key}
        if stage == PipelineStage.DRUM_TRANSCRIPTION:
            raw_midi = self._put(job_id, "midi/raw_drum.mid", b"MThd mock raw midi\n", "audio/midi")
            events = self._put(
                job_id,
                "midi/drum_events.json",
                json.dumps({"events": [{"time": 0.0, "drum": "kick"}]}).encode("utf-8"),
                "application/json",
            )
            return {"raw_midi": raw_midi.storage_key, "drum_events": events.storage_key}
        if stage == PipelineStage.MIDI_POST_PROCESSING:
            artifact = self._put(job_id, "midi/processed_drum.mid", b"MThd mock processed midi\n", "audio/midi")
            return {"processed_midi": artifact.storage_key}
        if stage == PipelineStage.NOTATION_GENERATION:
            artifact = self._put(
                job_id,
                "notation/score.musicxml",
                b"<?xml version=\"1.0\"?><score-partwise version=\"4.0\" />\n",
                "application/vnd.recordare.musicxml+xml",
            )
            return {"musicxml": artifact.storage_key}
        if stage == PipelineStage.PDF_EXPORT:
            artifact = self._put(job_id, "exports/score.pdf", b"%PDF-1.4\n% mock pdf\n", "application/pdf")
            return {"pdf": artifact.storage_key}
        return {}

    def _mock_stage_status(self, stage: PipelineStage) -> str:
        if stage == PipelineStage.PDF_EXPORT:
            return "completed_with_warning"
        return "completed"

    def _mock_stage_report(self, stage: PipelineStage) -> dict:
        if stage == PipelineStage.PREPROCESSING:
            return {"warnings": []}
        if stage == PipelineStage.SOURCE_SEPARATION:
            return {"separator": "mock", "warnings": ["mock_ai_enabled"]}
        if stage == PipelineStage.STEM_VALIDATION:
            return {"warnings": []}
        if stage == PipelineStage.DRUM_TRANSCRIPTION:
            return {"transcriber": "mock", "event_count": 1, "warnings": ["mock_ai_enabled"]}
        if stage == PipelineStage.MIDI_POST_PROCESSING:
            return {
                "input_event_count": 1,
                "output_event_count": 1,
                "dropped_event_count": 0,
                "warnings": [],
            }
        if stage == PipelineStage.NOTATION_GENERATION:
            return {"event_count": 1, "measure_count": 1, "warnings": []}
        if stage == PipelineStage.PDF_EXPORT:
            return {
                "pdf": {
                    "status": "completed_with_warning",
                    "renderer": "mock",
                    "warnings": ["mock_pdf_completed_with_warning"],
                },
                "warnings": ["mock_pdf_completed_with_warning"],
            }
        return {"warnings": []}

    def _write_mock_metadata(self, session: Session, job_id: str, artifact_keys: dict[str, str]) -> None:
        if not self._drum_track_exists(session, job_id):
            session.execute(
                insert(drum_tracks).values(
                    id=str(uuid4()),
                    job_id=job_id,
                    drums_stem_storage_key=artifact_keys.get("drums_stem"),
                    raw_midi_storage_key=artifact_keys.get("raw_midi"),
                    processed_midi_storage_key=artifact_keys.get("processed_midi"),
                    drum_events_storage_key=artifact_keys.get("drum_events"),
                    estimated_bpm=120.0,
                    time_signature="4/4",
                    event_count=1,
                    confidence_label=ConfidenceLabel.MEDIUM.value,
                    warnings=[],
                )
            )
        export_specs = (
            (ExportFileType.MIDI.value, artifact_keys["processed_midi"], "audio/midi"),
            (ExportFileType.MUSICXML.value, artifact_keys["musicxml"], "application/vnd.recordare.musicxml+xml"),
            (ExportFileType.PDF.value, artifact_keys["pdf"], "application/pdf"),
        )
        for export_type, storage_key, content_type in export_specs:
            if self._export_exists(session, job_id, export_type):
                continue
            stat = self.storage.put_bytes(storage_key, self._read_existing(storage_key), content_type)
            session.execute(
                insert(export_files).values(
                    id=str(uuid4()),
                    job_id=job_id,
                    type=export_type,
                    status=ExportFileStatus.AVAILABLE.value,
                    storage_key=storage_key,
                    content_type=content_type,
                    file_size_bytes=stat.file_size_bytes,
                    checksum=stat.checksum,
                )
            )

    def _drum_track_exists(self, session: Session, job_id: str) -> bool:
        return session.execute(select(drum_tracks.c.id).where(drum_tracks.c.job_id == job_id)).first() is not None

    def _export_exists(self, session: Session, job_id: str, export_type: str) -> bool:
        return (
            session.execute(
                select(export_files.c.id).where(
                    export_files.c.job_id == job_id,
                    export_files.c.type == export_type,
                )
            ).first()
            is not None
        )

    def _put(self, job_id: str, suffix: str, content: bytes, content_type: str) -> StoredArtifact:
        return self.storage.put_bytes(job_artifact_key(job_id, suffix), content, content_type)

    def _read_existing(self, storage_key: str) -> bytes:
        path = self.storage.root / storage_key
        return path.read_bytes()

    def _write_pipeline_log(self, job_id: str, pipeline_log: PipelineLog) -> StoredArtifact:
        return self.storage.put_bytes(
            job_artifact_key(job_id, "logs/pipeline.json"),
            pipeline_log.to_json_bytes(),
            "application/json",
        )

    def _maybe_fail(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise PipelineStageError(stage, f"mock failure at {stage}")

    def _serialize_stage_error(self, exc: Exception, stage: str) -> dict[str, str]:
        return {
            "type": exc.__class__.__name__,
            "code": getattr(exc, "code", exc.__class__.__name__),
            "message": str(exc),
            "stage": getattr(exc, "stage", stage),
        }
