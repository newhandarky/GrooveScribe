from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.review_timeline_service import ReviewTimelineService
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
