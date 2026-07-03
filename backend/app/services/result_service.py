from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus
from app.services.job_query_service import JobQueryService
from app.services.pipeline_log_read_model import PipelineLogReadService
from app.storage.base import StorageAdapter
from app.storage.errors import ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError

_QUALITY_FLAG_CODES = {
    "too_few_events",
    "sparse_transcription",
    "hihat_missing_likely",
    "mostly_tom_output",
    "no_snare_detected",
}


class ResultService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageAdapter | None = None,
        job_query_service: JobQueryService | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.job_query_service = job_query_service or JobQueryService()

    def get_completed_result(self, db: Session, job_id: str) -> TranscriptionJob:
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
        if job.status != JobStatus.COMPLETED:
            raise ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": job_id, "status": job.status.value})
        return job

    def preview_musicxml_url(self, job: TranscriptionJob) -> str | None:
        export_file = next(
            (
                export
                for export in job.export_files
                if export.type == ExportFileType.MUSICXML and export.status == ExportFileStatus.AVAILABLE
            ),
            None,
        )
        if export_file is None:
            return None
        return self.download_url(job.id, ExportFileType.MUSICXML.value)

    def download_url(self, job_id: str, export_type: str) -> str:
        return f"{self.settings.api_v1_prefix}/transcriptions/{job_id}/download/{export_type}"

    def pipeline_summary(self, job: TranscriptionJob) -> dict | None:
        pipeline_log = None
        if self.storage is not None:
            try:
                pipeline_log = PipelineLogReadService(storage=self.storage).get_optional_pipeline_log(job.id)
            except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError, ValueError):
                pipeline_log = None

        mode = "mock" if job.drum_track and job.drum_track.confidence_label else "unknown"
        stage_summaries = []
        warnings: list[str] = []
        if pipeline_log is not None:
            for stage in pipeline_log.stage_reports:
                stage_warnings = [warning for warning in stage.warnings if _is_public_safe_text(warning)]
                warnings.extend(stage_warnings)
                stage_summaries.append(
                    {
                        "name": stage.name,
                        "status": stage.status,
                        "runtime_seconds": stage.runtime_seconds,
                        "warnings": stage_warnings,
                    }
                )
            if pipeline_log.status:
                mode = _infer_pipeline_mode(job, stage_summaries)

        if job.drum_track:
            warnings.extend(warning for warning in job.drum_track.warnings if _is_public_safe_text(warning))

        return {
            "mode": mode,
            "status": pipeline_log.status if pipeline_log else None,
            "stages": stage_summaries,
            "artifacts": [
                {
                    "type": export.type.value,
                    "available": export.status == ExportFileStatus.AVAILABLE,
                    "file_size_bytes": export.file_size_bytes,
                    "status": export.status.value,
                }
                for export in sorted(job.export_files, key=lambda item: item.type.value)
            ],
            "warnings": sorted(set(warnings)),
            "quality": _pipeline_quality_summary(pipeline_log, job),
            "pipeline_log_available": pipeline_log is not None,
        }


def _infer_pipeline_mode(job: TranscriptionJob, stages: list[dict]) -> str:
    if job.drum_track and job.drum_track.confidence_label:
        return "mock"
    stage_names = {stage["name"] for stage in stages}
    if {"source_separation", "drum_transcription"} & stage_names:
        return "true_ai"
    return "unknown"


def _is_public_safe_text(value: str) -> bool:
    lowered = value.lower()
    return not any(
        token in lowered
        for token in (
            "traceback",
            "/users/",
            "/tmp/",
            "/private/tmp/",
            "/var/folders/",
            "stderr",
            "stdout",
            "command",
        )
    )


def _pipeline_quality_summary(pipeline_log, job: TranscriptionJob) -> dict | None:
    if pipeline_log is not None and pipeline_log.quality:
        return _sanitize_quality_summary(pipeline_log.quality)

    if pipeline_log is not None:
        for stage in pipeline_log.stage_reports:
            if stage.name == "midi_post_processing":
                summary = _quality_from_midi_report(stage.report)
                if summary is not None:
                    return summary

    if job.drum_track is None:
        return None
    flags = [warning for warning in job.drum_track.warnings if _is_public_safe_text(warning)]
    return {
        "raw_event_count": None,
        "processed_event_count": job.drum_track.event_count,
        "raw_note_histogram": {},
        "processed_drum_counts": {},
        "duration_seconds": job.audio_file.duration_seconds,
        "tempo_bpm": job.drum_track.estimated_bpm,
        "estimated_measure_count": None,
        "quality_flags": _quality_flag_subset(flags),
        "warnings": sorted(set(flags)),
    }


def _quality_from_midi_report(report: dict) -> dict | None:
    if not report:
        return None
    warnings = [item for item in _string_list(report.get("warnings")) if _is_public_safe_text(item)]
    return {
        "raw_event_count": _int_or_none(report.get("input_event_count")),
        "processed_event_count": _int_or_none(report.get("output_event_count")),
        "raw_note_histogram": _int_dict(report.get("raw_note_histogram")),
        "processed_drum_counts": _int_dict(report.get("processed_drum_counts")),
        "duration_seconds": None,
        "tempo_bpm": _float_or_none(report.get("estimated_bpm")),
        "estimated_measure_count": None,
        "quality_flags": _quality_flag_subset(_string_list(report.get("quality_flags")) or warnings),
        "warnings": sorted(set(warnings)),
    }


def _sanitize_quality_summary(raw: dict) -> dict:
    warnings = [item for item in _string_list(raw.get("warnings")) if _is_public_safe_text(item)]
    flags = [item for item in _string_list(raw.get("quality_flags")) if _is_public_safe_text(item)]
    return {
        "raw_event_count": _int_or_none(raw.get("raw_event_count")),
        "processed_event_count": _int_or_none(raw.get("processed_event_count")),
        "raw_note_histogram": _int_dict(raw.get("raw_note_histogram")),
        "processed_drum_counts": _int_dict(raw.get("processed_drum_counts")),
        "duration_seconds": _float_or_none(raw.get("duration_seconds")),
        "tempo_bpm": _float_or_none(raw.get("tempo_bpm")),
        "estimated_measure_count": _int_or_none(raw.get("estimated_measure_count")),
        "quality_flags": _quality_flag_subset(flags),
        "warnings": sorted(set(warnings)),
    }


def _quality_flag_subset(warnings: list[str]) -> list[str]:
    return sorted({warning for warning in warnings if warning in _QUALITY_FLAG_CODES})


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        parsed = _int_or_none(item)
        if parsed is not None:
            result[str(key)] = parsed
    return dict(sorted(result.items()))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_public_safe_text(str(item))]


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
