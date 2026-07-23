from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob

PIPELINE_MODE_DEMO_MOCK = "demo_mock"
PIPELINE_MODE_GENERIC_BASELINE = "generic_baseline"
# Kept only to identify and serialize historical jobs. It is not a public mode.
PIPELINE_MODE_TRUE_AI = "true_ai"
PIPELINE_MODE_UNKNOWN = "unknown"
ADTOF_PRESET_SEPARATED_V1 = "separated_v1"
TOM_FILTER_PRESET_V1 = "tom_guard_v1"
RUNTIME_FALLBACK_NOT_REQUIRED = "not_required"
RUNTIME_FALLBACK_NOT_APPLIED = "not_applied"

PUBLIC_PIPELINE_MODES = {
    PIPELINE_MODE_DEMO_MOCK,
    PIPELINE_MODE_GENERIC_BASELINE,
}


@dataclass(frozen=True)
class PipelineConfigSelection:
    pipeline_mode: str | None = None
    adtof_threshold_preset: str | None = None
    tom_filter_preset: str | None = None
    runtime_fallback_status: str | None = None
    source_job_id: str | None = None


def normalize_pipeline_config(
    *,
    pipeline_mode: str | None = None,
    adtof_threshold_preset: str | None = None,
    tom_filter_preset: str | None = None,
    source_job_id: str | None = None,
) -> PipelineConfigSelection:
    mode = _clean(pipeline_mode)
    adtof_preset = _clean(adtof_threshold_preset)
    tom_preset = _clean(tom_filter_preset)
    source_id = _clean(source_job_id)

    if mode is None:
        mode = PIPELINE_MODE_GENERIC_BASELINE
    if adtof_preset or tom_preset:
        raise ApiErrorException(
            ErrorCode.VALIDATION_ERROR,
            details={"field": "pipeline_config", "reason": "adtof_and_tom_presets_are_offline_only"},
        )
    if mode not in PUBLIC_PIPELINE_MODES:
        raise ApiErrorException(
            ErrorCode.VALIDATION_ERROR,
            details={"field": "pipeline_mode", "supported": sorted(PUBLIC_PIPELINE_MODES)},
        )
    return PipelineConfigSelection(
        pipeline_mode=mode,
        runtime_fallback_status=RUNTIME_FALLBACK_NOT_REQUIRED,
        source_job_id=source_id,
    )


def pipeline_config_for_job(job: TranscriptionJob) -> dict:
    mode = job.pipeline_mode or _legacy_mode(job)
    return {
        "mode": mode,
        "adtof_threshold_preset": job.adtof_threshold_preset,
        "tom_filter_preset": job.tom_filter_preset,
        "runtime_fallback_status": job.runtime_fallback_status,
        "source_job_id": job.source_job_id,
    }


def _legacy_mode(job: TranscriptionJob) -> str:
    if job.drum_transcriber == "mock" or job.source_separator == "mock":
        return PIPELINE_MODE_DEMO_MOCK
    if job.drum_transcriber or job.source_separator:
        return PIPELINE_MODE_TRUE_AI
    return PIPELINE_MODE_UNKNOWN


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
