from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ai_pipeline.notation.musescore import MuseScoreVisualQaRenderer
from ai_pipeline.notation.validation import validate_score_artifacts


def _musicxml(path: Path) -> Path:
    path.write_text('<score-partwise version="3.1"><part><measure><note/></measure></part></score-partwise>', encoding="utf-8")
    return path


def test_visual_qa_writes_pdf_and_first_page_png(monkeypatch, tmp_path: Path) -> None:
    musicxml = _musicxml(tmp_path / "score.musicxml")

    def runner(command, **_kwargs):
        output = Path(command[2])
        output.write_bytes(b"%PDF-1.4" if output.suffix == ".pdf" else b"\x89PNG\r\n\x1a\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("ai_pipeline.notation.musescore.shutil.which", lambda _value: "/usr/bin/mscore")
    result = MuseScoreVisualQaRenderer(renderer_binary="mscore", runner=runner).render(musicxml, tmp_path / "render")

    assert result.status == "completed"
    assert result.reason_code is None
    assert result.pdf_path is not None and result.pdf_path.is_file()
    assert result.first_page_png_path is not None and result.first_page_png_path.is_file()
    assert result.report() == {
        "status": "completed",
        "reason_code": None,
        "pdf_available": True,
        "first_page_png_available": True,
    }


def test_visual_qa_classifies_macos_gui_session_without_leaking_stderr(monkeypatch, tmp_path: Path) -> None:
    musicxml = _musicxml(tmp_path / "score.musicxml")
    raw_stderr = "PasteBoard: Error creating pasteboard /Users/private hiservices-xpcservice"

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=raw_stderr)

    monkeypatch.setattr("ai_pipeline.notation.musescore.shutil.which", lambda _value: "/opt/homebrew/bin/mscore")
    result = MuseScoreVisualQaRenderer(renderer_binary="mscore", runner=runner).render(musicxml, tmp_path / "render")
    validation = validate_score_artifacts(musicxml, visual_qa=result.report())

    assert result.status == "musescore_gui_session_unavailable"
    assert result.reason_code == "musescore_gui_session_unavailable"
    assert validation["musicxml"]["parseable"] is True
    assert validation["visual_qa"]["status"] == "musescore_gui_session_unavailable"
    payload = json.dumps({"result": result.report(), "validation": validation})
    assert "/Users/" not in payload
    assert "PasteBoard" not in payload
    assert "hiservices-xpcservice" not in payload


def test_visual_qa_distinguishes_renderer_unavailable_and_render_failure(monkeypatch, tmp_path: Path) -> None:
    musicxml = _musicxml(tmp_path / "score.musicxml")
    monkeypatch.setattr("ai_pipeline.notation.musescore.shutil.which", lambda _value: None)
    unavailable = MuseScoreVisualQaRenderer(renderer_binary="missing").render(musicxml, tmp_path / "missing")

    def failed_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="renderer failed")

    monkeypatch.setattr("ai_pipeline.notation.musescore.shutil.which", lambda _value: "/usr/bin/mscore")
    failed = MuseScoreVisualQaRenderer(renderer_binary="mscore", runner=failed_runner).render(musicxml, tmp_path / "failed")

    assert unavailable.report() == {
        "status": "renderer_unavailable",
        "reason_code": "renderer_not_found",
        "pdf_available": False,
        "first_page_png_available": False,
    }
    assert failed.report() == {
        "status": "render_failed",
        "reason_code": "renderer_nonzero_exit",
        "pdf_available": False,
        "first_page_png_available": False,
    }
