from app.services.pipeline_log_read_model import PipelineLogReadService, parse_pipeline_log_payload
from app.storage.local import LocalStorageAdapter


def test_parse_phase1_local_runner_pipeline_log() -> None:
    payload = {
        "schema_version": "1.0",
        "status": "completed",
        "artifacts": {"drum_events": "/tmp/job/midi/drum_events.json"},
        "quality": {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "quality_flags": ["hihat_missing_likely"],
        },
        "validation": {
            "musicxml": {"available": True, "parseable": True, "error_code": None, "warnings": []},
            "pdf": {
                "available": False,
                "optional": True,
                "openable": None,
                "error_code": "pdf_unavailable",
                "warnings": ["pdf_optional_unavailable"],
            },
        },
        "stages": [
            {
                "name": "notation_generation",
                "status": "completed",
                "runtime_seconds": 0.12,
                "artifacts": {"musicxml": "/tmp/job/notation/score.musicxml"},
                "report": {
                    "pdf": {
                        "status": "completed_with_warning",
                        "warnings": ["renderer_nonzero_exit"],
                    }
                },
            }
        ],
    }

    result = parse_pipeline_log_payload(payload)

    assert result.status == "completed"
    assert result.artifact_keys["drum_events"] == "/tmp/job/midi/drum_events.json"
    assert result.quality["raw_event_count"] == 7
    assert result.quality["quality_flags"] == ["hihat_missing_likely"]
    assert result.validation["musicxml"]["parseable"] is True
    assert result.validation["pdf"]["error_code"] == "pdf_unavailable"
    assert result.stage_reports[0].name == "notation_generation"
    assert result.stage_reports[0].warnings == ["renderer_nonzero_exit"]


def test_parse_worker_stage_reports_pipeline_log() -> None:
    payload = {
        "schema_version": "1.0",
        "job_id": "job-1",
        "events": [],
        "stage_reports": [
            {
                "name": "drum_transcription",
                "status": "failed",
                "error": {
                    "code": "DRUM_TRANSCRIPTION_FAILED",
                    "message": "failed",
                    "stage": "drum_transcription",
                },
            }
        ],
    }

    result = parse_pipeline_log_payload(payload)

    assert result.job_id == "job-1"
    assert result.stage_reports[0].status == "failed"
    assert result.stage_reports[0].error["code"] == "DRUM_TRANSCRIPTION_FAILED"


def test_pipeline_log_read_service_reads_job_log_from_storage(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    storage.put_bytes(
        b'{"job_id": "job-1", "stage_reports": [{"name": "pdf_export", "status": "completed"}]}',
        "jobs/job-1/logs/pipeline.json",
        "application/json",
    )

    result = PipelineLogReadService(storage=storage).get_pipeline_log("job-1")

    assert result.job_id == "job-1"
    assert result.stage_reports[0].name == "pdf_export"


def test_pipeline_log_read_service_optional_returns_none_when_missing(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")

    result = PipelineLogReadService(storage=storage).get_optional_pipeline_log("missing")

    assert result is None
