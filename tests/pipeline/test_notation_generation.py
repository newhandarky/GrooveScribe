import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ai_pipeline.notation.musicxml import MusicXmlGenerator
from ai_pipeline.notation.pdf import MuseScorePdfExporter


def _write_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "ticks_per_beat": 480,
        "estimated_bpm": 120.0,
        "time_signature": "4/4",
        "event_count": 3,
        "events": [
            {"index": 0, "tick": 0, "beat": 0.0, "drum": "kick", "midi_note": 36, "velocity": 100},
            {"index": 1, "tick": 120, "beat": 0.25, "drum": "snare", "midi_note": 38, "velocity": 90},
            {"index": 2, "tick": 240, "beat": 0.5, "drum": "closed_hat", "midi_note": 42, "velocity": 80},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_musicxml_generator_writes_parseable_score(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    assert result.musicxml_path.exists()
    root = ET.parse(result.musicxml_path).getroot()
    assert root.tag == "score-partwise"
    assert root.find("./part/measure/note") is not None
    assert result.event_count == 3


def test_pdf_exporter_reports_missing_renderer(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    try:
        MuseScorePdfExporter(renderer_binary="definitely-not-musescore").export(
            musicxml.musicxml_path,
            tmp_path / "notation",
        )
    except Exception as exc:
        assert getattr(exc, "code") == "PDF_RENDERER_NOT_AVAILABLE"
    else:
        raise AssertionError("expected PDF_RENDERER_NOT_AVAILABLE")
