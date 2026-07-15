import json
import zipfile
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.base import Base
from app.models import AudioFile, DrumTrack, ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType, JobStatus, PipelineStage
from app.schemas.transcriptions import PipelineSummaryResult, TranscriptionResultResponse
from app.services.download_service import DownloadService
from app.services.job_query_service import JobQueryService
from app.services.result_service import ResultService, _sanitize_performance_gate, _sanitize_validation_summary
from app.services.review_packet_service import ReviewPacketService
from app.storage.keys import build_job_artifact_key
from app.storage.local import LocalStorageAdapter
from app.storage.types import ArtifactType

UNSAFE_TOKENS = (
    "/Users/",
    "/tmp/",
    "/private/tmp/",
    "/var/folders/",
    "Traceback",
    "stdout",
    "stderr",
    "raw command",
    "command_template",
)


def test_visual_qa_validation_is_public_safe_and_does_not_change_musicxml_status() -> None:
    summary = _sanitize_validation_summary(
        {
            "musicxml": {"available": True, "parseable": True, "warnings": []},
            "pdf": {"available": False, "optional": True, "openable": None, "warnings": []},
            "visual_qa": {
                "status": "musescore_gui_session_unavailable",
                "reason_code": "musescore_gui_session_unavailable",
                "pdf_available": False,
                "first_page_png_available": False,
                "stderr": "/Users/private /tmp/command_template",
            },
        }
    )

    assert summary is not None
    assert summary["musicxml"]["parseable"] is True
    assert summary["visual_qa"] == {
        "status": "musescore_gui_session_unavailable",
        "reason_code": "musescore_gui_session_unavailable",
        "pdf_available": False,
        "first_page_png_available": False,
    }
    assert not any(token.lower() in json.dumps(summary).lower() for token in UNSAFE_TOKENS)


def test_performance_gate_is_public_safe_and_keeps_not_ready_state() -> None:
    gate = _sanitize_performance_gate(
        {
            "verdict": "performance_ready",
            "delivery_allowed": True,
            "blocking_issues": ["/tmp/leaked", "audio_onset_alignment_low"],
            "midi": {"parseable": True, "debug_path": "/Users/private"},
            "audio_alignment": {"status": "measured", "onset_alignment_rate": 0.72, "command_template": "secret"},
        }
    )

    assert gate == {
        "schema_version": "1.0",
        "verdict": "performance_ready",
        "delivery_allowed": True,
        "ground_truth_verified": False,
        "real_audio_verified": False,
        "delivery_status": "technical_artifacts_only",
        "blocking_issues": ["audio_onset_alignment_low"],
        "midi": {"parseable": True},
        "musicxml": {},
        "rhythm": {},
        "playability": {},
        "audio_alignment": {"status": "measured", "onset_alignment_rate": 0.72},
    }


def test_performance_gate_keeps_needs_better_source_without_leaking_runtime_details() -> None:
    gate = _sanitize_performance_gate(
        {
            "verdict": "needs_better_source",
            "delivery_allowed": False,
            "blocking_issues": ["source_signal_insufficient", "/Users/private/input.wav"],
            "audio_alignment": {"status": "unavailable", "stderr": "private runtime detail"},
        }
    )

    assert gate["verdict"] == "needs_better_source"
    assert gate["delivery_allowed"] is False
    assert gate["blocking_issues"] == ["source_signal_insufficient"]
    assert gate["audio_alignment"] == {"status": "unavailable"}


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_job(
    session: Session,
    *,
    status: JobStatus = JobStatus.QUEUED,
    stage: PipelineStage = PipelineStage.QUEUED,
    export_status: ExportFileStatus | None = None,
    export_type: ExportFileType = ExportFileType.MIDI,
    storage_key: str = "jobs/job-1/midi/processed_drum.mid",
) -> TranscriptionJob:
    audio = AudioFile(
        id="audio-1",
        original_filename="demo.wav",
        content_type="audio/wav",
        file_size_bytes=8,
        duration_seconds=30.0,
        original_storage_key="jobs/job-1/original/demo.wav",
    )
    job = TranscriptionJob(
        id="job-1",
        audio_file=audio,
        status=status,
        stage=stage,
        progress=100 if status == JobStatus.COMPLETED else 0,
        title="Demo",
    )
    session.add(job)
    if status == JobStatus.COMPLETED:
        session.add(
            DrumTrack(
                id="track-1",
                job=job,
                processed_midi_storage_key="jobs/job-1/midi/processed_drum.mid",
                event_count=4,
                warnings=[],
            )
        )
    if export_status is not None:
        session.add(
            ExportFile(
                id="export-1",
                job=job,
                type=export_type,
                status=export_status,
                storage_key=storage_key,
                content_type="audio/midi" if export_type == ExportFileType.MIDI else "application/octet-stream",
                file_size_bytes=4,
            )
        )
    session.commit()
    return job


def test_job_status_service_returns_stage_message() -> None:
    with _session() as session:
        _create_job(session)
        service = JobQueryService()

        job = service.get_job_or_raise(session, "job-1")

        assert job.status == JobStatus.QUEUED
        assert service.stage_message(job) == "任務已排隊，等待開始分析。"


def test_job_status_service_not_found_raises_job_not_found() -> None:
    with _session() as session:
        service = JobQueryService()

        try:
            service.get_job_or_raise(session, "missing")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.JOB_NOT_FOUND
        else:
            raise AssertionError("expected JOB_NOT_FOUND")


def test_job_status_failed_error_payload_includes_retriable() -> None:
    with _session() as session:
        job = _create_job(session, status=JobStatus.FAILED, stage=PipelineStage.FAILED)
        job.error_code = ErrorCode.PIPELINE_FAILED
        job.error_message = "音訊分析流程失敗，請稍後再試或重新上傳音檔。"
        job.error_stage = PipelineStage.DRUM_TRANSCRIPTION.value
        session.commit()
        service = JobQueryService()

        error = service.error_payload(job)

        assert error == {
            "code": ErrorCode.PIPELINE_FAILED,
            "message": "音訊分析流程失敗，請稍後再試或重新上傳音檔。",
            "stage": PipelineStage.DRUM_TRANSCRIPTION.value,
            "retriable": True,
        }


def test_result_service_returns_completed_job_with_related_metadata() -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings())

        job = service.get_completed_result(session, "job-1")

        assert job.audio_file.original_filename == "demo.wav"
        assert job.drum_track.event_count == 4
        assert service.download_url(job.id, "midi") == "/api/v1/transcriptions/job-1/download/midi"


def test_result_service_builds_redacted_pipeline_summary(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "stages": [
            {
              "name": "midi_post_processing",
              "status": "completed",
              "runtime_seconds": 1.25,
              "report": {
                "warnings": ["too_few_events", "command_failed", "/Users/private/path"]
              }
            }
          ],
          "artifacts": {"processed_midi": "jobs/job-1/midi/processed_drum.mid"}
          ,
          "quality": {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "raw_note_histogram": {"35": 1, "47": 6},
            "processed_drum_counts": {"kick": 1, "tom": 6},
            "duration_seconds": 12.5,
            "tempo_bpm": 118.2,
            "estimated_measure_count": 6,
            "notation_readability": {
              "schema_version": "1.0",
              "layout_profile": "standard_drum_v1",
              "voice_count": 2,
              "has_hand_voice": true,
              "has_foot_voice": true,
              "hand_event_count": 5,
              "foot_event_count": 2,
              "generic_tom_count": 6,
              "measure_count": 6,
              "dense_measure_count": 1,
              "dense_measure_threshold": 24,
              "warnings": ["notation_dense_full_mix_likely", "/tmp/private"]
            },
            "notation_chart": {
              "schema_version": "1.0",
              "mode": "readable_drum_chart_v2",
              "readability_verdict": "readable_chart_candidate",
              "original_event_count": 80,
              "chart_event_count": 24,
              "max_events_per_measure": 8,
              "max_visible_notes_per_measure": 8,
              "measure_count": 8,
              "groove_measure_count": 5,
              "repeat_measure_count": 2,
              "fill_measure_count": 1,
              "accent_measure_count": 1,
              "preserved_counts": {"kick": 8, "snare": 8, "closed_hat": 8, "/tmp/private": 1},
              "dropped_counts": {"tom": 20, "cymbal": 12},
              "dense_measures_before": 4,
              "dense_measures_after": 0,
              "warnings": ["notation_tom_reduced_for_readability", "/tmp/private"]
            },
            "quality_flags": ["hihat_missing_likely", "mostly_tom_output", "/tmp/private"],
            "warnings": ["hihat_missing_likely", "stderr leaked"],
            "postprocess_filters": {
              "tom_false_positive": {
                "enabled": true,
                "preset": "tom_guard_v1",
                "status": "applied",
                "input_tom_count": 6,
                "output_tom_count": 4,
                "dropped_tom_count": 2,
                "target_max_tom_ratio": 0.3,
                "input_event_count": 16,
                "output_event_count": 14,
                "debug_path": "/tmp/private"
              }
            },
            "quality_verdict": {
              "verdict": "draft_candidate_needs_review",
              "usability_score": 3,
              "limitations": ["tom_false_positive_likely", "/tmp/private"],
              "candidate_gate": {
                "status": "passed",
                "run_completed": true,
                "processed_event_count": 7,
                "min_event_count": 4,
                "kick_present": true,
                "snare_present": true,
                "hihat_present": true,
                "blocking_flags": [],
                "musicxml_available": true,
                "musicxml_parseable": true
              }
            }
          },
          "validation": {
            "musicxml": {
              "available": true,
              "parseable": true,
              "error_code": null,
              "warnings": ["command_template leaked"]
            },
            "pdf": {
              "available": false,
              "optional": true,
              "openable": null,
              "error_code": "pdf_unavailable",
              "warnings": ["pdf_optional_unavailable", "/Users/private/path", "Traceback leaked"]
            }
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        job = _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings(), storage=storage)

        summary = service.pipeline_summary(job)

        assert summary["pipeline_log_available"] is True
        assert summary["mode"] == "unknown"
        assert summary["config"] == {
            "mode": "unknown",
            "adtof_threshold_preset": None,
            "tom_filter_preset": None,
            "runtime_fallback_status": None,
            "source_job_id": None,
        }
        assert summary["stages"] == [
            {
                "name": "midi_post_processing",
                "status": "completed",
                "runtime_seconds": 1.25,
                "warnings": ["too_few_events", "command_failed"],
            }
        ]
        assert summary["artifacts"][0]["type"] == "midi"
        assert summary["quality"] == {
            "raw_event_count": 7,
            "processed_event_count": 7,
            "raw_note_histogram": {"35": 1, "47": 6},
            "processed_drum_counts": {"kick": 1, "tom": 6},
            "duration_seconds": 12.5,
            "tempo_bpm": 118.2,
            "estimated_measure_count": 6,
            "notation_readability": {
                "schema_version": "1.0",
                "layout_profile": "standard_drum_v1",
                "voice_count": 2,
                "has_hand_voice": True,
                "has_foot_voice": True,
                "hand_event_count": 5,
                "foot_event_count": 2,
                "generic_tom_count": 6,
                "measure_count": 6,
                "dense_measure_count": 1,
                "dense_measure_threshold": 24,
                "warnings": ["notation_dense_full_mix_likely"],
            },
            "notation_chart": {
                "schema_version": "1.0",
                "mode": "readable_drum_chart_v2",
                "readability_verdict": "readable_chart_candidate",
                "original_event_count": 80,
                "chart_event_count": 24,
                "max_events_per_measure": 8,
                "max_visible_notes_per_measure": 8,
                "measure_count": 8,
                "groove_measure_count": 5,
                "repeat_measure_count": 2,
                "fill_measure_count": 1,
                "accent_measure_count": 1,
                "preserved_counts": {"closed_hat": 8, "kick": 8, "snare": 8},
                "dropped_counts": {"cymbal": 12, "tom": 20},
                "dense_measures_before": 4,
                "dense_measures_after": 0,
                "warnings": ["notation_tom_reduced_for_readability"],
            },
            "quality_flags": ["hihat_missing_likely", "mostly_tom_output"],
            "warnings": ["hihat_missing_likely"],
            "postprocess_filters": {
                "tom_false_positive": {
                    "enabled": True,
                    "preset": "tom_guard_v1",
                    "status": "applied",
                    "input_tom_count": 6,
                    "output_tom_count": 4,
                    "dropped_tom_count": 2,
                    "target_max_tom_ratio": 0.3,
                    "input_event_count": 16,
                    "output_event_count": 14,
                }
            },
            "quality_verdict": {
                "verdict": "draft_candidate_needs_review",
                "usability_score": 3,
                "limitations": ["tom_false_positive_likely"],
                "candidate_gate": {
                    "status": "passed",
                    "run_completed": True,
                    "processed_event_count": 7,
                    "min_event_count": 4,
                    "kick_present": True,
                    "snare_present": True,
                    "hihat_present": True,
                    "blocking_flags": [],
                    "musicxml_available": True,
                    "musicxml_parseable": True,
                },
                "musicxml_available": True,
                "musicxml_parseable": True,
            },
        }
        assert summary["validation"] == {
            "musicxml": {
                "available": True,
                "parseable": True,
                "error_code": None,
                "warnings": [],
            },
            "pdf": {
                "available": False,
                "optional": True,
                "openable": None,
                "error_code": "pdf_unavailable",
                "warnings": ["pdf_optional_unavailable"],
            },
        }
        assert "/Users/" not in str(summary)
        assert "/tmp/" not in str(summary)
        assert "stderr" not in str(summary)
        assert "command_template" not in str(summary)
        assert "Traceback" not in str(summary)
        assert "command_failed" in str(summary)


def test_result_service_keeps_legacy_pipeline_log_without_validation_graceful(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "stages": [
            {
              "name": "notation_generation",
              "status": "completed",
              "runtime_seconds": 0.5,
              "report": {"warnings": ["legacy_warning"]}
            }
          ],
          "artifacts": {"musicxml": "jobs/job-1/notation/score.musicxml"}
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        job = _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings(), storage=storage)

        summary = service.pipeline_summary(job)
        model = PipelineSummaryResult(**summary)

        assert model.validation is None
        assert model.pipeline_log_available is True
        assert model.quality is not None
        assert model.quality.processed_event_count == 4
        assert model.quality.quality_verdict.verdict == "unknown"
        assert model.quality.quality_verdict.limitations == ["quality_verdict_unavailable"]


def test_transcription_result_response_allows_legacy_null_pipeline() -> None:
    response = TranscriptionResultResponse(
        job_id="job-1",
        status="completed",
        stage="completed",
        title="Demo",
        created_at="2026-07-03T00:00:00Z",
        completed_at="2026-07-03T00:01:00Z",
        audio={
            "id": "audio-1",
            "file_name": "demo.wav",
            "content_type": "audio/wav",
            "file_size_bytes": 10,
        },
        drum_track=None,
        preview={"musicxml_url": None},
        exports=[],
        pipeline=None,
    )

    assert response.pipeline is None


def test_result_service_quality_fallback_keeps_warning_and_flag_contract_separate(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "stages": [
            {
              "name": "midi_post_processing",
              "status": "completed",
              "runtime_seconds": 1.25,
              "report": {
                "input_event_count": 12,
                "output_event_count": 6,
                "raw_note_histogram": {"35": 2, "47": 10},
                "processed_drum_counts": {"kick": 2, "tom": 4},
                "estimated_bpm": 120,
                "warnings": ["too_few_events", "high_drop_ratio", "mock_ai_enabled"]
              }
            }
          ],
          "artifacts": {"processed_midi": "jobs/job-1/midi/processed_drum.mid"}
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        job = _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ResultService(settings=Settings(), storage=storage)

        summary = service.pipeline_summary(job)

        assert summary["quality"]["quality_flags"] == ["too_few_events"]
        assert summary["quality"]["warnings"] == ["high_drop_ratio", "mock_ai_enabled", "too_few_events"]
        assert summary["quality"]["quality_verdict"]["verdict"] == "unknown"


def test_public_transcription_openapi_does_not_expose_storage_or_raw_diagnostics() -> None:
    from app.main import create_app

    openapi = create_app().openapi()
    public_schema = {
        name: openapi["components"]["schemas"][name]
        for name in (
            "TranscriptionResultResponse",
            "PipelineSummaryResult",
            "PipelineValidationSummary",
            "PipelineArtifactValidation",
            "ReviewPacketResponse",
        )
    }
    schema_text = json.dumps(public_schema)

    assert "PipelineValidationSummary" in schema_text
    assert "storage_key" not in schema_text
    for unsafe in UNSAFE_TOKENS:
        assert unsafe.lower() not in schema_text.lower()


def test_result_service_rejects_non_completed_job() -> None:
    with _session() as session:
        _create_job(session, status=JobStatus.PROCESSING, stage=PipelineStage.SOURCE_SEPARATION)
        service = ResultService(settings=Settings())

        try:
            service.get_completed_result(session, "job-1")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.JOB_NOT_COMPLETED
        else:
            raise AssertionError("expected JOB_NOT_COMPLETED")


def test_download_service_opens_available_export(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = DownloadService(storage=storage)

        artifact = service.open_export(session, job_id="job-1", export_type="midi")

        try:
            assert artifact.content_type == "audio/midi"
            assert artifact.filename == "processed_drum.mid"
            assert artifact.reader.read() == b"midi"
        finally:
            artifact.reader.close()


def test_download_service_uses_performance_filename_for_performance_export(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    performance_key = "jobs/job-1/notation/performance_score.mid"
    storage.put_bytes(b"performance", performance_key, "audio/midi")
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
            storage_key=performance_key,
        )
        service = DownloadService(storage=storage)

        artifact = service.open_export(session, job_id="job-1", export_type="midi")

        try:
            assert artifact.filename == "performance_score.mid"
            assert artifact.reader.read() == b"performance"
        finally:
            artifact.reader.close()


def test_download_service_rejects_pending_export(tmp_path) -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.PENDING,
        )
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="midi")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_READY
        else:
            raise AssertionError("expected EXPORT_NOT_READY")


def test_download_service_rejects_missing_export(tmp_path) -> None:
    with _session() as session:
        _create_job(session, status=JobStatus.COMPLETED, stage=PipelineStage.COMPLETED)
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="pdf")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_FOUND
        else:
            raise AssertionError("expected EXPORT_NOT_FOUND")


def test_download_service_maps_missing_storage_artifact_to_export_not_found(tmp_path) -> None:
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = DownloadService(storage=LocalStorageAdapter(tmp_path))

        try:
            service.open_export(session, job_id="job-1", export_type="midi")
        except ApiErrorException as exc:
            assert exc.code == ErrorCode.EXPORT_NOT_FOUND
        else:
            raise AssertionError("expected EXPORT_NOT_FOUND")


def test_review_packet_service_builds_public_safe_packet_and_zip(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
    storage.put_bytes(b"<score-partwise />", "jobs/job-1/notation/score.musicxml", "application/vnd.recordare.musicxml+xml")
    storage.put_bytes(
        b'{"schema_version":"1.0","measures":[{"render_kind":"groove_anchor"}]}',
        "jobs/job-1/notation/chart_events.json",
        "application/json",
    )
    storage.put_bytes(b"\x89PNG\r\n\x1a\n", "jobs/job-1/notation/score_preview.png", "image/png")
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "quality": {
            "raw_event_count": 7,
            "processed_event_count": 4,
            "raw_note_histogram": {"35": 2, "38": 2},
            "processed_drum_counts": {"kick": 2, "snare": 2},
            "quality_flags": ["too_few_events"],
            "warnings": ["too_few_events", "/Users/private/path"]
          },
          "validation": {
            "musicxml": {"available": true, "parseable": true, "error_code": null, "warnings": []},
            "pdf": {"available": false, "optional": true, "openable": null, "error_code": "pdf_unavailable", "warnings": ["pdf_optional_unavailable"]},
            "visual_qa": {"status": "musescore_gui_session_unavailable", "reason_code": "musescore_gui_session_unavailable", "pdf_available": false, "first_page_png_available": false}
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        session.add(
            ExportFile(
                id="export-2",
                job_id="job-1",
                type=ExportFileType.MUSICXML,
                status=ExportFileStatus.AVAILABLE,
                storage_key="jobs/job-1/notation/score.musicxml",
                content_type="application/vnd.recordare.musicxml+xml",
                file_size_bytes=18,
            )
        )
        session.add(
            ExportFile(
                id="export-3",
                job_id="job-1",
                type=ExportFileType.PDF,
                status=ExportFileStatus.FAILED,
                storage_key="jobs/job-1/exports/score.pdf",
                content_type="application/pdf",
                file_size_bytes=None,
            )
        )
        session.commit()
        service = ReviewPacketService(settings=Settings(), storage=storage)

        packet = service.build_packet(session, job_id="job-1")
        packet_zip = service.build_zip(session, job_id="job-1")

    assert packet["schema_version"] == "1.0"
    assert packet["status"] == "ready"
    assert packet["manual_eval_seed"]["baseline_report_ref"] == "review:job-1"
    assert packet["pipeline_config"] == {
        "mode": "unknown",
        "adtof_threshold_preset": None,
        "tom_filter_preset": None,
        "runtime_fallback_status": None,
        "source_job_id": None,
    }
    assert packet["manual_eval_seed"]["processed_event_count"] == 4
    assert packet["validation"]["pdf"]["status"] == "optional_unavailable"
    assert packet["validation"]["visual_qa"]["status"] == "musescore_gui_session_unavailable"
    assert any(item["code"] == "pdf_optional" for item in packet["review_checklist"])
    assert packet["redaction"] == {"status": "passed", "unsafe_token_count": 0}
    assert "/Users/" not in json.dumps(packet)
    with zipfile.ZipFile(BytesIO(packet_zip.content)) as archive:
        assert sorted(archive.namelist()) == [
            "chart_events.json",
            "drums.mid",
            "review_notes.md",
            "review_packet.json",
            "score.musicxml",
            "score_preview.png",
        ]
        assert b"groove_anchor" in archive.read("chart_events.json")
        assert archive.read("drums.mid") == b"midi"
        assert b"review:job-1" in archive.read("review_packet.json")


def test_review_packet_service_drops_unsafe_dict_keys_from_public_packet_and_zip(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "quality": {
            "raw_event_count": 9,
            "processed_event_count": 6,
            "raw_note_histogram": {
              "35": 2,
              "/Users/private": 1,
              "/tmp/foo": 1,
              "Traceback": 1,
              "command_template": 1
            },
            "processed_drum_counts": {
              "kick": 4,
              "snare": 2,
              "/Users/private": 7,
              "/tmp/foo": 8,
              "Traceback": 9,
              "stdout": 10,
              "command_template": 11
            },
            "quality_flags": [],
            "warnings": []
          },
          "validation": {
            "musicxml": {"available": true, "parseable": true, "error_code": null, "warnings": []},
            "pdf": {"available": false, "optional": true, "openable": null, "error_code": "pdf_unavailable", "warnings": ["pdf_optional_unavailable"]}
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ReviewPacketService(settings=Settings(), storage=storage)

        packet = service.build_packet(session, job_id="job-1")
        packet_zip = service.build_zip(session, job_id="job-1")

    packet_text = json.dumps(packet, ensure_ascii=False)
    assert packet["quality"]["processed_drum_counts"] == {"kick": 4, "snare": 2}
    assert packet["manual_eval_seed"]["processed_drum_counts"] == {"kick": 4, "snare": 2}
    assert packet["quality"]["raw_note_histogram"] == {"35": 2}
    assert packet["redaction"] == {"status": "passed", "unsafe_token_count": 0}
    for token in UNSAFE_TOKENS:
        assert token not in packet_text

    with zipfile.ZipFile(BytesIO(packet_zip.content)) as archive:
        zipped_packet = archive.read("review_packet.json").decode("utf-8")
    for token in UNSAFE_TOKENS:
        assert token not in zipped_packet
    assert json.loads(zipped_packet)["manual_eval_seed"]["processed_drum_counts"] == {"kick": 4, "snare": 2}


def test_review_packet_notes_do_not_verify_inconsistent_performance_gate(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(b"midi", "jobs/job-1/midi/processed_drum.mid", "audio/midi")
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "quality": {
            "performance_gate": {
              "verdict": "performance_ready",
              "delivery_allowed": true,
              "delivery_status": "technical_artifacts_only"
            }
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ReviewPacketService(settings=Settings(), storage=storage)

        packet = service.build_packet(session, job_id="job-1")
        notes = service.build_notes_markdown(packet)

    assert "缺少完整 verified delivery contract" in notes
    assert "已通過已校準的自動交付 gate" not in notes


def test_review_packet_zip_keeps_processed_midi_as_a_separate_diagnostic_artifact(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    performance_key = "jobs/job-1/notation/performance_score.mid"
    processed_key = "jobs/job-1/midi/processed_drum.mid"
    storage.put_bytes(b"performance-score", performance_key, "audio/midi")
    storage.put_bytes(b"processed-events", processed_key, "audio/midi")
    storage.put_bytes(
        b"""
        {
          "status": "completed",
          "quality": {
            "performance_gate": {
              "verdict": "performance_ready",
              "delivery_allowed": true,
              "delivery_status": "verified_performance_score"
            }
          }
        }
        """,
        build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG),
        "application/json",
    )
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
            storage_key=performance_key,
        )
        service = ReviewPacketService(settings=Settings(), storage=storage)
        packet_zip = service.build_zip(session, job_id="job-1")

    with zipfile.ZipFile(BytesIO(packet_zip.content)) as archive:
        assert archive.read("performance_score.mid") == b"performance-score"
        assert archive.read("processed_drum.mid") == b"processed-events"


def test_review_packet_service_marks_missing_export_artifact_unavailable(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    with _session() as session:
        _create_job(
            session,
            status=JobStatus.COMPLETED,
            stage=PipelineStage.COMPLETED,
            export_status=ExportFileStatus.AVAILABLE,
        )
        service = ReviewPacketService(settings=Settings(), storage=storage)

        packet = service.build_packet(session, job_id="job-1")

    midi = next(item for item in packet["exports"] if item["type"] == "midi")
    assert midi["status"] == "unavailable"
    assert midi["download_url"] is None
    assert midi["included_in_zip"] is False
