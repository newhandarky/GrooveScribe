from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.storage.base import StorageAdapter
from app.storage.errors import ArtifactNotFoundError
from app.storage.keys import build_job_artifact_key
from app.storage.types import ArtifactType


@dataclass(frozen=True)
class StageReportReadModel:
    name: str
    status: str
    runtime_seconds: float | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class PipelineLogReadModel:
    job_id: str | None
    status: str | None
    artifact_keys: dict[str, str]
    stage_reports: list[StageReportReadModel]
    quality: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    candidate_analysis: dict[str, Any] = field(default_factory=dict)


class PipelineLogReadService:
    def __init__(self, *, storage: StorageAdapter) -> None:
        self.storage = storage

    def get_pipeline_log(self, job_id: str) -> PipelineLogReadModel:
        storage_key = build_job_artifact_key(job_id, ArtifactType.PIPELINE_LOG)
        with self.storage.open_reader(storage_key) as reader:
            payload = json.loads(reader.read().decode("utf-8"))
        return parse_pipeline_log_payload(payload)

    def get_optional_pipeline_log(self, job_id: str) -> PipelineLogReadModel | None:
        try:
            return self.get_pipeline_log(job_id)
        except ArtifactNotFoundError:
            return None


def parse_pipeline_log_payload(payload: dict[str, Any]) -> PipelineLogReadModel:
    raw_reports = payload.get("stages") or payload.get("stage_reports") or []
    stage_reports = [_parse_stage_report(raw_report) for raw_report in raw_reports]
    return PipelineLogReadModel(
        job_id=payload.get("job_id"),
        status=payload.get("status"),
        artifact_keys=_string_dict(payload.get("artifacts")),
        stage_reports=stage_reports,
        quality=_dict(payload.get("quality")),
        validation=_dict(payload.get("validation")),
        candidate_analysis=_dict(payload.get("candidate_analysis")),
    )


def _parse_stage_report(raw_report: dict[str, Any]) -> StageReportReadModel:
    report = _dict(raw_report.get("report"))
    return StageReportReadModel(
        name=str(raw_report.get("name") or raw_report.get("stage") or ""),
        status=str(raw_report.get("status") or ""),
        runtime_seconds=_float_or_none(raw_report.get("runtime_seconds")),
        artifacts=_string_dict(raw_report.get("artifacts")),
        report=report,
        warnings=_collect_warnings(report),
        error=_dict_or_none(raw_report.get("error")),
    )


def _collect_warnings(report: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    raw_warnings = report.get("warnings")
    if isinstance(raw_warnings, list):
        warnings.extend(str(warning) for warning in raw_warnings)

    pdf_report = report.get("pdf")
    if isinstance(pdf_report, dict):
        pdf_warnings = pdf_report.get("warnings")
        if isinstance(pdf_warnings, list):
            warnings.extend(str(warning) for warning in pdf_warnings)
    return warnings


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
