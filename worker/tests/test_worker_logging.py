from __future__ import annotations

import json
import logging

from app.logging import PipelineLog, log_event


def test_worker_log_event_includes_job_stage_event_and_duration(caplog) -> None:
    caplog.set_level(logging.INFO, logger="groovescribe.worker")

    log_event(job_id="job-1", event="stage_completed", stage="preprocessing", duration_seconds=1.2345)

    payload = json.loads(caplog.records[0].message)
    assert payload == {
        "duration_seconds": 1.234,
        "event": "stage_completed",
        "job_id": "job-1",
        "stage": "preprocessing",
    }


def test_pipeline_log_serializes_reviewable_artifact() -> None:
    pipeline_log = PipelineLog(job_id="job-1")

    pipeline_log.add("stage_started", stage="preprocessing")

    payload = json.loads(pipeline_log.to_json_bytes())
    assert payload == {
        "job_id": "job-1",
        "events": [{"event": "stage_started", "stage": "preprocessing"}],
    }
