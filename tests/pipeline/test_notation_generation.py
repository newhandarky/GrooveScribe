import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ai_pipeline.local_runner import LocalPipelineConfig, LocalPipelineRunner
from ai_pipeline.notation.musicxml import MusicXmlGenerator
from ai_pipeline.notation.pdf import MuseScorePdfExporter
from ai_pipeline.notation.validation import validate_musicxml_artifact, validate_pdf_artifact


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


def test_score_artifact_validation_reports_musicxml_and_optional_pdf(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    musicxml_validation = validate_musicxml_artifact(musicxml.musicxml_path)
    pdf_validation = validate_pdf_artifact(None)

    assert musicxml_validation == {"available": True, "parseable": True, "error_code": None, "warnings": []}
    assert pdf_validation == {
        "available": False,
        "optional": True,
        "openable": None,
        "error_code": "pdf_unavailable",
        "warnings": ["pdf_optional_unavailable"],
    }


def test_score_artifact_validation_rejects_invalid_musicxml_and_pdf_header(tmp_path) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    pdf_path = tmp_path / "score.pdf"
    musicxml_path.write_text("<not-score />", encoding="utf-8")
    pdf_path.write_bytes(b"not pdf")

    musicxml_validation = validate_musicxml_artifact(musicxml_path)
    pdf_validation = validate_pdf_artifact(pdf_path)

    assert musicxml_validation["available"] is True
    assert musicxml_validation["parseable"] is True
    assert "musicxml_root_unexpected" in musicxml_validation["warnings"]
    assert pdf_validation["openable"] is False
    assert pdf_validation["error_code"] == "pdf_header_invalid"


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


def test_pdf_exporter_accepts_nonzero_exit_when_pdf_exists(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    def runner(command, **kwargs):
        pdf_path = Path(command[2])
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return subprocess.CompletedProcess(command, 1, "", "renderer shutdown warning")

    result = MuseScorePdfExporter(
        renderer_binary=sys.executable,
        runner=runner,
    ).export(musicxml.musicxml_path, tmp_path / "notation")

    assert result.pdf_path.exists()
    assert result.warnings
    assert result.warnings[0].startswith("renderer_nonzero_exit:")


def test_pdf_exporter_fails_nonzero_exit_without_pdf(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "renderer failed")

    try:
        MuseScorePdfExporter(
            renderer_binary=sys.executable,
            runner=runner,
        ).export(musicxml.musicxml_path, tmp_path / "notation")
    except Exception as exc:
        assert getattr(exc, "code") == "PDF_EXPORT_FAILED"
    else:
        raise AssertionError("expected PDF_EXPORT_FAILED")


def test_local_runner_writes_validation_summary_to_pipeline_log(tmp_path) -> None:
    source = Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav")
    output_dir = tmp_path / "output"

    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True)).run(source, output_dir)

    payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert payload["validation"]["musicxml"]["parseable"] is True
    assert payload["validation"]["pdf"] == {
        "available": False,
        "optional": True,
        "openable": None,
        "error_code": "pdf_unavailable",
        "warnings": ["pdf_optional_unavailable"],
    }
