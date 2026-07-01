from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob
from app.models.enums import ExportFileType
from app.services.pipeline_log_read_model import PipelineLogReadModel, PipelineLogReadService, StageReportReadModel
from app.storage.base import StorageAdapter
from app.storage.keys import build_job_artifact_key
from app.storage.types import ArtifactType


@dataclass(frozen=True)
class InternalJobErrorReadModel:
    code: str | None = None
    message: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class InternalJobPipelineReadModel:
    job_id: str
    status: str
    failed_stage: str | None
    artifacts: dict[str, str]
    stage_reports: list[StageReportReadModel]
    warnings: list[str] = field(default_factory=list)
    completed_with_warning: bool = False
    error: InternalJobErrorReadModel | None = None
    pipeline_log_found: bool = False
    pipeline_mode: str = "unknown"
    mock_ai: bool | None = None


class InternalJobDetailService:
    def __init__(
        self,
        *,
        storage: StorageAdapter,
        pipeline_log_service: PipelineLogReadService | None = None,
    ) -> None:
        self.pipeline_log_service = pipeline_log_service or PipelineLogReadService(storage=storage)

    def get_pipeline_snapshot(self, db: Session, job_id: str) -> InternalJobPipelineReadModel:
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
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})

        pipeline_log = self.pipeline_log_service.get_optional_pipeline_log(job_id)
        stage_reports = pipeline_log.stage_reports if pipeline_log else []
        artifacts = self._artifact_keys(job, pipeline_log)
        error = self._error(job, stage_reports)
        mock_ai = self._mock_ai(job, stage_reports)

        return InternalJobPipelineReadModel(
            job_id=job.id,
            status=job.status.value,
            failed_stage=job.error_stage or _first_failed_stage(stage_reports),
            artifacts=artifacts,
            stage_reports=stage_reports,
            warnings=self._warnings(job, stage_reports),
            completed_with_warning=_has_completed_with_warning(stage_reports),
            error=error,
            pipeline_log_found=pipeline_log is not None,
            pipeline_mode=self._pipeline_mode(job, mock_ai),
            mock_ai=mock_ai,
        )

    def _artifact_keys(self, job: TranscriptionJob, pipeline_log: PipelineLogReadModel | None) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        if job.audio_file.original_storage_key:
            artifacts["original_audio"] = job.audio_file.original_storage_key
        if job.audio_file.normalized_storage_key:
            artifacts["normalized_audio"] = job.audio_file.normalized_storage_key

        drum_track = job.drum_track
        if drum_track:
            if drum_track.drums_stem_storage_key:
                artifacts["drums_stem"] = drum_track.drums_stem_storage_key
            if drum_track.raw_midi_storage_key:
                artifacts["raw_midi"] = drum_track.raw_midi_storage_key
            if drum_track.processed_midi_storage_key:
                artifacts["processed_midi"] = drum_track.processed_midi_storage_key
            if drum_track.drum_events_storage_key:
                artifacts["drum_events"] = drum_track.drum_events_storage_key

        for export_file in job.export_files:
            if export_file.type == ExportFileType.MUSICXML:
                artifacts["musicxml"] = export_file.storage_key
            elif export_file.type == ExportFileType.PDF:
                artifacts["pdf"] = export_file.storage_key
            elif export_file.type == ExportFileType.MIDI:
                artifacts.setdefault("processed_midi", export_file.storage_key)

        if pipeline_log:
            artifacts.update(pipeline_log.artifact_keys)
        if pipeline_log is not None:
            artifacts.setdefault("pipeline_log", build_job_artifact_key(job.id, ArtifactType.PIPELINE_LOG))
        return artifacts

    def _warnings(self, job: TranscriptionJob, stage_reports: list[StageReportReadModel]) -> list[str]:
        warnings: list[str] = []
        if job.drum_track:
            warnings.extend(job.drum_track.warnings or [])
        for stage_report in stage_reports:
            warnings.extend(stage_report.warnings)
        return _dedupe(warnings)

    def _error(
        self,
        job: TranscriptionJob,
        stage_reports: list[StageReportReadModel],
    ) -> InternalJobErrorReadModel | None:
        if job.error_code or job.error_message or job.error_stage:
            return InternalJobErrorReadModel(
                code=job.error_code,
                message=job.error_message,
                stage=job.error_stage,
            )
        for stage_report in stage_reports:
            if stage_report.error:
                return InternalJobErrorReadModel(
                    code=_string_or_none(stage_report.error.get("code")),
                    message=_string_or_none(stage_report.error.get("message")),
                    stage=_string_or_none(stage_report.error.get("stage")) or stage_report.name,
                )
        return None

    def _mock_ai(self, job: TranscriptionJob, stage_reports: list[StageReportReadModel]) -> bool | None:
        configured_components = [job.source_separator, job.drum_transcriber]
        if any(component == "mock" for component in configured_components):
            return True
        if any(component for component in configured_components):
            return False
        for stage_report in stage_reports:
            if "mock_ai_enabled" in stage_report.warnings:
                return True
            if _report_contains_value(stage_report.report, "mock"):
                return True
        return None

    def _pipeline_mode(self, job: TranscriptionJob, mock_ai: bool | None) -> str:
        if mock_ai is True:
            return "mock"
        if mock_ai is False:
            return "true"
        if job.pipeline_version:
            return job.pipeline_version
        return "unknown"


def _has_completed_with_warning(stage_reports: list[StageReportReadModel]) -> bool:
    for stage_report in stage_reports:
        if stage_report.status == "completed_with_warning":
            return True
        pdf_report = stage_report.report.get("pdf")
        if isinstance(pdf_report, dict) and pdf_report.get("status") == "completed_with_warning":
            return True
    return False


def _first_failed_stage(stage_reports: list[StageReportReadModel]) -> str | None:
    for stage_report in stage_reports:
        if stage_report.status == "failed":
            return stage_report.name
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _report_contains_value(report: dict[str, Any], expected: str) -> bool:
    for value in report.values():
        if value == expected:
            return True
        if isinstance(value, dict) and _report_contains_value(value, expected):
            return True
    return False
