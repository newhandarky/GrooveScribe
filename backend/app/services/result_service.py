from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus
from app.services.job_query_service import JobQueryService
from app.services.pipeline_config import PIPELINE_MODE_DEMO_MOCK, PIPELINE_MODE_TRUE_AI, pipeline_config_for_job
from app.services.pipeline_log_read_model import PipelineLogReadService
from app.services.review_timeline_service import ReviewTimelineService
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

    def review_audio_url(self, job: TranscriptionJob, audio_kind: str) -> str | None:
        if self.storage is None:
            return None
        if audio_kind == "original":
            storage_key = job.audio_file.original_storage_key
        elif audio_kind == "drums_stem" and job.drum_track:
            storage_key = job.drum_track.drums_stem_storage_key
        else:
            return None
        try:
            if not storage_key or not self.storage.exists(storage_key):
                return None
        except Exception:
            return None
        return f"{self.settings.api_v1_prefix}/transcriptions/{job.id}/review-audio/{audio_kind}"

    def review_timeline(self, job: TranscriptionJob) -> dict:
        if self.storage is None:
            return {"schema_version": "1.0", "timing_source": "unavailable", "tempo_bpm": None, "audio_sources": [], "measures": []}
        return ReviewTimelineService(storage=self.storage).build(
            job,
            audio_urls={
                "original": self.review_audio_url(job, "original"),
                "drums_stem": self.review_audio_url(job, "drums_stem"),
            },
        )

    def pipeline_summary(self, job: TranscriptionJob) -> dict | None:
        pipeline_log = None
        if self.storage is not None:
            try:
                pipeline_log = PipelineLogReadService(storage=self.storage).get_optional_pipeline_log(job.id)
            except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError, ValueError):
                pipeline_log = None

        pipeline_config = _pipeline_config_summary(job, pipeline_log)
        mode = _mode_from_pipeline_config(pipeline_config) or ("mock" if job.drum_track and job.drum_track.confidence_label else "unknown")
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
                mode = _mode_from_pipeline_config(pipeline_config) or _infer_pipeline_mode(job, stage_summaries)

        if job.drum_track:
            warnings.extend(warning for warning in job.drum_track.warnings if _is_public_safe_text(warning))

        validation = _pipeline_validation_summary(pipeline_log)
        quality = _pipeline_quality_summary(pipeline_log, job, validation)
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
            "config": pipeline_config,
            "quality": quality,
            "validation": validation,
            "pipeline_log_available": pipeline_log is not None,
        }


def _infer_pipeline_mode(job: TranscriptionJob, stages: list[dict]) -> str:
    if job.drum_track and job.drum_track.confidence_label:
        return "mock"
    stage_names = {stage["name"] for stage in stages}
    if {"source_separation", "drum_transcription"} & stage_names:
        return "true_ai"
    return "unknown"


def _pipeline_config_summary(job: TranscriptionJob, pipeline_log) -> dict:
    config = pipeline_config_for_job(job)
    if pipeline_log is not None and pipeline_log.quality:
        logged_config = pipeline_log.quality.get("pipeline_config") if isinstance(pipeline_log.quality, dict) else None
        if isinstance(logged_config, dict):
            config.update(_sanitize_pipeline_config(logged_config))
    return _sanitize_pipeline_config(config)


def _sanitize_pipeline_config(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        "mode": _safe_code(value.get("mode")) or "unknown",
        "adtof_threshold_preset": _safe_code(value.get("adtof_threshold_preset")),
        "tom_filter_preset": _safe_code(value.get("tom_filter_preset")),
        "runtime_fallback_status": _safe_code(value.get("runtime_fallback_status")),
        "source_job_id": _safe_code(value.get("source_job_id")),
    }


def _mode_from_pipeline_config(config: dict) -> str | None:
    mode = config.get("mode")
    if mode == PIPELINE_MODE_TRUE_AI:
        return "true_ai"
    if mode == PIPELINE_MODE_DEMO_MOCK:
        return "mock"
    return None


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
            "command_template",
            "raw command",
        )
    )


def _pipeline_quality_summary(pipeline_log, job: TranscriptionJob, validation: dict | None = None) -> dict | None:
    if pipeline_log is not None and pipeline_log.quality:
        return _with_quality_verdict(_sanitize_quality_summary(pipeline_log.quality), validation)

    if pipeline_log is not None:
        for stage in pipeline_log.stage_reports:
            if stage.name == "midi_post_processing":
                summary = _quality_from_midi_report(stage.report)
                if summary is not None:
                    return _with_quality_verdict(summary, validation)

    if job.drum_track is None:
        return None
    flags = [warning for warning in job.drum_track.warnings if _is_public_safe_text(warning)]
    summary = {
        "raw_event_count": None,
        "processed_event_count": job.drum_track.event_count,
        "raw_note_histogram": {},
        "processed_drum_counts": {},
        "duration_seconds": job.audio_file.duration_seconds,
        "tempo_bpm": job.drum_track.estimated_bpm,
        "tempo_source": None,
        "estimated_measure_count": None,
        "musicxml_parseable": None,
        "visual_qa_status": None,
        "visual_qa_reason_code": None,
        "notation_readability": {},
        "notation_chart": {},
        "quality_flags": _quality_flag_subset(flags),
        "warnings": sorted(set(flags)),
        "postprocess_filters": {},
    }
    return _with_quality_verdict(summary, validation)


def _pipeline_validation_summary(pipeline_log) -> dict | None:
    if pipeline_log is None:
        return None
    if pipeline_log.validation:
        return _sanitize_validation_summary(pipeline_log.validation)
    for stage in pipeline_log.stage_reports:
        if stage.name == "notation_generation":
            validation = stage.report.get("validation")
            if isinstance(validation, dict):
                return _sanitize_validation_summary(validation)
    return None


def _sanitize_validation_summary(raw: dict) -> dict | None:
    musicxml = _sanitize_validation_item(raw.get("musicxml"), artifact="musicxml")
    pdf = _sanitize_validation_item(raw.get("pdf"), artifact="pdf")
    visual_qa = _sanitize_visual_qa(raw.get("visual_qa"))
    if musicxml is None and pdf is None and visual_qa is None:
        return None
    summary = {
        "musicxml": musicxml
        or {
            "available": False,
            "parseable": False,
            "error_code": "musicxml_unavailable",
            "warnings": ["musicxml_unavailable"],
        },
        "pdf": pdf
        or {
            "available": False,
            "optional": True,
            "openable": None,
            "error_code": "pdf_unavailable",
            "warnings": ["pdf_optional_unavailable"],
        },
    }
    if visual_qa is not None:
        summary["visual_qa"] = visual_qa
    return summary


def _sanitize_visual_qa(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    status = _safe_code(value.get("status"))
    if status not in {
        "completed",
        "musescore_gui_session_unavailable",
        "renderer_unavailable",
        "render_failed",
        "not_requested",
    }:
        status = "not_requested"
    reason_code = _safe_code(value.get("reason_code"))
    return {
        "status": status,
        "reason_code": reason_code,
        "pdf_available": bool(value.get("pdf_available")),
        "first_page_png_available": bool(value.get("first_page_png_available")),
    }


def _sanitize_validation_item(value: object, *, artifact: str) -> dict | None:
    if not isinstance(value, dict):
        return None
    warnings = [item for item in _string_list(value.get("warnings")) if _is_public_safe_text(item)]
    error_code = _safe_code(value.get("error_code"))
    if artifact == "pdf":
        return {
            "available": bool(value.get("available")),
            "optional": bool(value.get("optional", True)),
            "openable": _bool_or_none(value.get("openable")),
            "error_code": error_code,
            "warnings": warnings,
        }
    return {
        "available": bool(value.get("available")),
        "parseable": _bool_or_none(value.get("parseable")),
        "error_code": error_code,
        "warnings": warnings,
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
        "tempo_source": None,
        "estimated_measure_count": None,
        "musicxml_parseable": None,
        "visual_qa_status": None,
        "visual_qa_reason_code": None,
        "notation_readability": {},
        "notation_chart": {},
        "quality_flags": _quality_flag_subset(_string_list(report.get("quality_flags")) or warnings),
        "warnings": sorted(set(warnings)),
        "postprocess_filters": _sanitize_postprocess_filters(report.get("postprocess_filters")),
    }


def _sanitize_quality_summary(raw: dict) -> dict:
    warnings = [item for item in _string_list(raw.get("warnings")) if _is_public_safe_text(item)]
    flags = [item for item in _string_list(raw.get("quality_flags")) if _is_public_safe_text(item)]
    quality = {
        "raw_event_count": _int_or_none(raw.get("raw_event_count")),
        "processed_event_count": _int_or_none(raw.get("processed_event_count")),
        "raw_note_histogram": _int_dict(raw.get("raw_note_histogram")),
        "processed_drum_counts": _int_dict(raw.get("processed_drum_counts")),
        "duration_seconds": _float_or_none(raw.get("duration_seconds")),
        "tempo_bpm": _float_or_none(raw.get("tempo_bpm")),
        "estimated_measure_count": _int_or_none(raw.get("estimated_measure_count")),
        "notation_readability": _sanitize_notation_readability(raw.get("notation_readability")),
        "notation_chart": _sanitize_notation_chart(raw.get("notation_chart")),
        "quality_flags": _quality_flag_subset(flags),
        "warnings": sorted(set(warnings)),
        "postprocess_filters": _sanitize_postprocess_filters(raw.get("postprocess_filters")),
    }
    for key, sanitizer in (
        ("musicxml_parseable", _bool_or_none),
        ("visual_qa_status", _safe_code),
        ("visual_qa_reason_code", _safe_code),
        ("tempo_source", _safe_code),
    ):
        if key in raw:
            quality[key] = sanitizer(raw.get(key))
    raw_verdict = raw.get("quality_verdict")
    if isinstance(raw_verdict, dict):
        quality["quality_verdict"] = _sanitize_quality_verdict(raw_verdict)
    if isinstance(raw.get("performance_gate"), dict):
        quality["performance_gate"] = _sanitize_performance_gate(raw.get("performance_gate"))
    return quality


def _with_quality_verdict(quality: dict, validation: dict | None) -> dict:
    verdict = quality.get("quality_verdict")
    if isinstance(verdict, dict):
        quality["quality_verdict"] = _sanitize_quality_verdict(verdict)
        return quality
    quality["quality_verdict"] = _unknown_quality_verdict(validation)
    return quality


def _sanitize_quality_verdict(raw: dict) -> dict:
    gate = raw.get("candidate_gate") if isinstance(raw.get("candidate_gate"), dict) else {}
    musicxml_available = bool(raw.get("musicxml_available", gate.get("musicxml_available", False)))
    musicxml_parseable = bool(raw.get("musicxml_parseable", gate.get("musicxml_parseable", False)))
    return {
        "verdict": _safe_code(raw.get("verdict")) or "unknown",
        "usability_score": _int_or_none(raw.get("usability_score")),
        "limitations": [item for item in _string_list(raw.get("limitations")) if _is_public_safe_text(item)],
        "candidate_gate": {
            "status": _safe_code(gate.get("status")) or "unknown",
            "run_completed": _bool_or_none(gate.get("run_completed")),
            "processed_event_count": _int_or_none(gate.get("processed_event_count")),
            "min_event_count": _int_or_none(gate.get("min_event_count")),
            "kick_present": _bool_or_none(gate.get("kick_present")),
            "snare_present": _bool_or_none(gate.get("snare_present")),
            "hihat_present": _bool_or_none(gate.get("hihat_present")),
            "blocking_flags": [item for item in _string_list(gate.get("blocking_flags")) if _is_public_safe_text(item)],
            "musicxml_available": musicxml_available,
            "musicxml_parseable": musicxml_parseable,
        },
        "musicxml_available": musicxml_available,
        "musicxml_parseable": musicxml_parseable,
    }


def _sanitize_performance_gate(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    verdict = _safe_code(value.get("verdict")) or "not_ready"
    if verdict not in {"performance_ready", "playable_but_low_confidence", "not_ready"}:
        verdict = "not_ready"
    def safe_section(name: str) -> dict:
        section = value.get(name)
        if not isinstance(section, dict):
            return {}
        return {
            str(key): item
            for key, item in section.items()
            if isinstance(item, (str, int, float, bool, type(None)))
            and _is_public_safe_text(str(item))
            and not any(token in str(key).lower() for token in ("path", "command", "template", "stderr", "stdout"))
        }
    return {
        "schema_version": _safe_code(value.get("schema_version")) or "1.0",
        "verdict": verdict,
        "delivery_allowed": bool(value.get("delivery_allowed")),
        "ground_truth_verified": bool(value.get("ground_truth_verified")),
        "blocking_issues": [item for item in _string_list(value.get("blocking_issues")) if _is_public_safe_text(item)],
        "midi": safe_section("midi"),
        "musicxml": safe_section("musicxml"),
        "rhythm": safe_section("rhythm"),
        "playability": safe_section("playability"),
        "audio_alignment": safe_section("audio_alignment"),
    }


def _sanitize_notation_readability(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        "schema_version": _safe_code(value.get("schema_version")) or "1.0",
        "layout_profile": _safe_code(value.get("layout_profile")) or "unknown",
        "voice_count": _int_or_none(value.get("voice_count")),
        "has_hand_voice": bool(value.get("has_hand_voice")),
        "has_foot_voice": bool(value.get("has_foot_voice")),
        "hand_event_count": _int_or_none(value.get("hand_event_count")),
        "foot_event_count": _int_or_none(value.get("foot_event_count")),
        "generic_tom_count": _int_or_none(value.get("generic_tom_count")),
        "measure_count": _int_or_none(value.get("measure_count")),
        "dense_measure_count": _int_or_none(value.get("dense_measure_count")),
        "dense_measure_threshold": _int_or_none(value.get("dense_measure_threshold")),
        "warnings": [item for item in _string_list(value.get("warnings")) if _is_public_safe_text(item)],
    }


def _sanitize_notation_chart(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    sanitized = {
        "schema_version": _safe_code(value.get("schema_version")) or "1.0",
        "mode": _safe_code(value.get("mode")) or "unknown",
        "readability_verdict": _safe_code(value.get("readability_verdict")) or "unknown",
        "original_event_count": _int_or_none(value.get("original_event_count")),
        "chart_event_count": _int_or_none(value.get("chart_event_count")),
        "max_events_per_measure": _int_or_none(value.get("max_events_per_measure")),
        "max_visible_notes_per_measure": _int_or_none(value.get("max_visible_notes_per_measure")),
        "measure_count": _int_or_none(value.get("measure_count")),
        "groove_measure_count": _int_or_none(value.get("groove_measure_count")),
        "repeat_measure_count": _int_or_none(value.get("repeat_measure_count")),
        "fill_measure_count": _int_or_none(value.get("fill_measure_count")),
        "accent_measure_count": _int_or_none(value.get("accent_measure_count")),
        "preserved_counts": _safe_int_dict(value.get("preserved_counts")),
        "dropped_counts": _safe_int_dict(value.get("dropped_counts")),
        "dense_measures_before": _int_or_none(value.get("dense_measures_before")),
        "dense_measures_after": _int_or_none(value.get("dense_measures_after")),
        "warnings": [item for item in _string_list(value.get("warnings")) if _is_public_safe_text(item)],
    }
    for key in (
        "anchor_measure_count",
        "literal_measure_count",
        "break_measure_count",
        "stable_groove_section_count",
        "complete_core_groove_measure_count",
        "incomplete_core_groove_measure_count",
        "hihat_rendered_measure_count",
        "measures_with_complete_core_groove",
        "groove_eighth_note_count",
        "groove_sixteenth_note_count",
        "fill_sixteenth_note_count",
        "off_grid_events_snapped",
        "off_grid_events_dropped",
        "measures_with_fragmented_rests",
        "hihat_eighth_pulse_measure_count",
        "hihat_quarter_pulse_measure_count",
    ):
        number = _int_or_none(value.get(key))
        if number is not None:
            sanitized[key] = number
    rhythm_mode = _safe_code(value.get("rhythm_mode"))
    if rhythm_mode:
        sanitized["rhythm_mode"] = rhythm_mode
    return sanitized


def _unknown_quality_verdict(validation: dict | None) -> dict:
    musicxml = validation.get("musicxml") if isinstance(validation, dict) and isinstance(validation.get("musicxml"), dict) else {}
    musicxml_available = bool(musicxml.get("available"))
    musicxml_parseable = bool(musicxml.get("parseable"))
    return {
        "verdict": "unknown",
        "usability_score": None,
        "limitations": ["quality_verdict_unavailable"],
        "candidate_gate": {
            "status": "unknown",
            "run_completed": None,
            "processed_event_count": None,
            "min_event_count": None,
            "kick_present": None,
            "snare_present": None,
            "hihat_present": None,
            "blocking_flags": [],
            "musicxml_available": musicxml_available,
            "musicxml_parseable": musicxml_parseable,
        },
        "musicxml_available": musicxml_available,
        "musicxml_parseable": musicxml_parseable,
    }


def _quality_flag_subset(warnings: list[str]) -> list[str]:
    return sorted({warning for warning in warnings if warning in _QUALITY_FLAG_CODES})


def _safe_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if _is_public_safe_text(text) else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        parsed = _int_or_none(item)
        if parsed is not None:
            result[str(key)] = parsed
    return dict(sorted(result.items()))


def _safe_int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        safe_key = _safe_code(key)
        parsed = _int_or_none(item)
        if safe_key is not None and parsed is not None:
            result[safe_key] = parsed
    return dict(sorted(result.items()))


def _sanitize_postprocess_filters(value: object) -> dict[str, dict]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict] = {}
    allowed_scalar_keys = {
        "enabled",
        "preset",
        "status",
        "input_tom_count",
        "output_tom_count",
        "dropped_tom_count",
        "target_max_tom_ratio",
        "input_event_count",
        "output_event_count",
    }
    for filter_name, summary in value.items():
        name = _safe_code(filter_name)
        if not name or not isinstance(summary, dict):
            continue
        clean_summary: dict[str, object] = {}
        for key, item in summary.items():
            safe_key = _safe_code(key)
            if not safe_key or safe_key not in allowed_scalar_keys:
                continue
            if isinstance(item, bool) or item is None:
                clean_summary[safe_key] = item
            elif isinstance(item, int | float) and not isinstance(item, bool):
                clean_summary[safe_key] = item
            elif isinstance(item, str) and _is_public_safe_text(item):
                clean_summary[safe_key] = item
        if clean_summary:
            result[name] = clean_summary
    return result


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
