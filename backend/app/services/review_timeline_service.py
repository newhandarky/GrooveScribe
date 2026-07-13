from __future__ import annotations

import json
from collections import Counter, defaultdict

from app.models import TranscriptionJob
from app.storage import ArtifactType, StorageAdapter, build_job_artifact_key
from app.storage.errors import ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError


class ReviewTimelineService:
    """Build API-safe, score-tempo measure cues for audio-assisted review."""

    def __init__(self, *, storage: StorageAdapter) -> None:
        self.storage = storage

    def build(self, job: TranscriptionJob, *, audio_urls: dict[str, str | None]) -> dict:
        chart_payload = self._chart_payload(job.id)
        summary = chart_payload.get("chart_summary") if isinstance(chart_payload, dict) else {}
        summary = summary if isinstance(summary, dict) else {}
        ticks_per_beat = _positive_int(chart_payload.get("ticks_per_beat"), 480)
        beats = _beats(chart_payload.get("time_signature"))
        tempo_bpm = _positive_float(chart_payload.get("tempo_bpm"), job.drum_track.estimated_bpm if job.drum_track else None)
        measure_ticks = ticks_per_beat * beats
        measure_count = _positive_int(summary.get("measure_count"), 0)
        events_by_measure: dict[int, Counter[str]] = defaultdict(Counter)
        for event in chart_payload.get("events", []) if isinstance(chart_payload, dict) else []:
            if not isinstance(event, dict):
                continue
            tick = event.get("tick")
            drum = event.get("drum")
            if isinstance(tick, int) and isinstance(drum, str) and drum in {"kick", "snare", "closed_hat", "open_hat", "tom", "cymbal"}:
                events_by_measure[tick // measure_ticks][drum] += 1
        render_kinds = {
            item.get("measure_index"): item.get("render_kind")
            for item in summary.get("chart_measures", [])
            if isinstance(item, dict) and isinstance(item.get("measure_index"), int) and isinstance(item.get("render_kind"), str)
        }
        measure_count = max(measure_count, max(events_by_measure.keys(), default=-1) + 1)
        seconds_per_measure = beats * 60 / tempo_bpm if tempo_bpm else None
        measures = [
            {
                "measure_index": index + 1,
                "start_seconds": round(index * seconds_per_measure, 3) if seconds_per_measure is not None else None,
                "end_seconds": round((index + 1) * seconds_per_measure, 3) if seconds_per_measure is not None else None,
                "render_kind": render_kinds.get(index, "unknown"),
                "drum_counts": dict(sorted(events_by_measure[index].items())),
                "warnings": _measure_warnings(render_kinds.get(index, "unknown"), events_by_measure[index]),
            }
            for index in range(measure_count)
        ]
        return {
            "schema_version": "1.0",
            "timing_source": "score_tempo" if seconds_per_measure is not None else "unavailable",
            "tempo_bpm": tempo_bpm,
            "audio_sources": [
                {
                    "kind": "original",
                    "label": "原始音訊",
                    "available": audio_urls.get("original") is not None,
                    "playback_url": audio_urls.get("original"),
                },
                {
                    "kind": "drums_stem",
                    "label": "分離鼓聲",
                    "available": audio_urls.get("drums_stem") is not None,
                    "playback_url": audio_urls.get("drums_stem"),
                },
            ],
            "measures": measures,
        }

    def _chart_payload(self, job_id: str) -> dict:
        key = build_job_artifact_key(job_id, ArtifactType.CHART_EVENTS)
        try:
            with self.storage.open_reader(key) as reader:
                payload = json.loads(reader.read().decode("utf-8"))
        except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _measure_warnings(render_kind: str, counts: Counter[str]) -> list[str]:
    warnings: list[str] = []
    if render_kind == "fill":
        warnings.append("review_fill_against_audio")
    if counts and not ({"kick", "snare", "closed_hat", "open_hat"} & set(counts)):
        warnings.append("no_core_groove_events")
    return warnings


def _positive_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default


def _positive_float(value: object, fallback: object) -> float | None:
    for candidate in (value, fallback):
        if isinstance(candidate, (int, float)) and candidate > 0:
            return float(candidate)
    return None


def _beats(value: object) -> int:
    try:
        beats = int(str(value or "4/4").split("/", 1)[0])
        return beats if beats > 0 else 4
    except ValueError:
        return 4
