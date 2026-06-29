from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


def get_worker_logger() -> logging.Logger:
    return logging.getLogger("groovescribe.worker")


def log_event(
    *,
    job_id: str,
    event: str,
    stage: str | None = None,
    duration_seconds: float | None = None,
    **metadata: Any,
) -> None:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "event": event,
    }
    if stage is not None:
        payload["stage"] = stage
    if duration_seconds is not None:
        payload["duration_seconds"] = round(duration_seconds, 3)
    payload.update({key: value for key, value in metadata.items() if value is not None})
    get_worker_logger().info(json.dumps(payload, sort_keys=True))


@dataclass
class PipelineLog:
    job_id: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, event: str, *, stage: str | None = None, **metadata: Any) -> None:
        record: dict[str, Any] = {"event": event}
        if stage is not None:
            record["stage"] = stage
        record.update({key: value for key, value in metadata.items() if value is not None})
        self.events.append(record)
        log_event(job_id=self.job_id, event=event, stage=stage, **metadata)

    def time_stage(self, stage: str):
        return _StageTimer(self, stage)

    def to_json_bytes(self) -> bytes:
        return json.dumps({"job_id": self.job_id, "events": self.events}, ensure_ascii=False, indent=2).encode(
            "utf-8"
        )


class _StageTimer:
    def __init__(self, pipeline_log: PipelineLog, stage: str) -> None:
        self.pipeline_log = pipeline_log
        self.stage = stage
        self.started_at = 0.0

    def __enter__(self):
        self.started_at = monotonic()
        self.pipeline_log.add("stage_started", stage=self.stage)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        duration = monotonic() - self.started_at
        event = "stage_failed" if exc is not None else "stage_completed"
        self.pipeline_log.add(event, stage=self.stage, duration_seconds=round(duration, 3))
        return False
