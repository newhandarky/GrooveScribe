from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.review_timeline_service import ReviewTimelineService
from app.services.result_service import _safe_drum_counts
from app.storage.keys import build_job_artifact_key
from app.storage.local import LocalStorageAdapter
from app.storage.types import ArtifactType


def test_review_timeline_keeps_all_playback_events_for_long_practice_tracks(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    events = [
        {"tick": index * 120, "drum": "kick", "velocity": 90}
        for index in range(2_050)
    ]
    storage.put_bytes(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "chart_summary": {"measure_count": 129},
                "events": events,
            }
        ).encode("utf-8"),
        build_job_artifact_key("job-1", ArtifactType.CHART_EVENTS),
        "application/json",
    )

    timeline = ReviewTimelineService(storage=storage).build(
        SimpleNamespace(id="job-1", drum_track=None),
        audio_urls={"original": None, "drums_stem": None, "accompaniment": None},
    )

    assert timeline["performance_playback"]["event_count"] == 2_050
    assert len(timeline["performance_playback"]["events"]) == 2_050


def test_review_timeline_preserves_generic_hi_hat_without_articulation(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "chart_summary": {"measure_count": 1},
                "events": [{"tick": 240, "drum": "hi_hat", "velocity": 80}],
            }
        ).encode("utf-8"),
        build_job_artifact_key("job-1", ArtifactType.CHART_EVENTS),
        "application/json",
    )

    timeline = ReviewTimelineService(storage=storage).build(
        SimpleNamespace(id="job-1", drum_track=None),
        audio_urls={"original": None, "drums_stem": None, "accompaniment": None},
    )

    assert timeline["measures"][0]["drum_counts"] == {"hi_hat": 1}
    assert timeline["performance_playback"]["events"][0]["drum"] == "hi_hat"


def test_legacy_hat_counts_and_chart_events_are_publicly_normalized(tmp_path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    storage.put_bytes(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "chart_summary": {"measure_count": 1},
                "events": [
                    {"tick": 0, "drum": "closed_hat", "velocity": 80},
                    {"tick": 240, "drum": "open_hat", "velocity": 80},
                    {"tick": 480, "drum": "pedal_hat", "velocity": 80},
                ],
            }
        ).encode("utf-8"),
        build_job_artifact_key("job-1", ArtifactType.CHART_EVENTS),
        "application/json",
    )

    timeline = ReviewTimelineService(storage=storage).build(
        SimpleNamespace(id="job-1", drum_track=None),
        audio_urls={"original": None, "drums_stem": None, "accompaniment": None},
    )

    assert _safe_drum_counts({"kick": 1, "closed_hat": 2, "open_hat": 3, "pedal_hat": 4}) == {"kick": 1, "hi_hat": 9}
    assert timeline["measures"][0]["drum_counts"] == {"hi_hat": 3}
    assert {event["drum"] for event in timeline["performance_playback"]["events"]} == {"hi_hat"}
