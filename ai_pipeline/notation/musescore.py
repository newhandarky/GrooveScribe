from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ai_pipeline.notation.types import MuseScoreVisualQaResult

CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

_GUI_SESSION_MARKERS = (
    "pasteboard",
    "hiservices-xpcservice",
    "connection invalid",
    "tisfileinterrogator",
)


class MuseScoreVisualQaRenderer:
    """Optional CLI renderer whose failures never invalidate MusicXML output."""

    def __init__(
        self,
        renderer_binary: str | None = None,
        timeout_seconds: int = 120,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.renderer_binary = renderer_binary
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def render(self, musicxml_path: Path, output_dir: Path) -> MuseScoreVisualQaResult:
        if not musicxml_path.is_file() or musicxml_path.stat().st_size <= 0:
            return MuseScoreVisualQaResult("render_failed", "musicxml_unavailable")
        renderer = self._resolve_renderer()
        if renderer is None:
            return MuseScoreVisualQaResult("renderer_unavailable", "renderer_not_found")

        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / "score.pdf"
        png_path = output_dir / "score_preview.png"
        for output_path, missing_reason in ((pdf_path, "pdf_not_created"), (png_path, "png_not_created")):
            completed, reason = self._run(renderer, output_path, musicxml_path)
            if reason is not None:
                status = "renderer_unavailable" if reason == "renderer_unavailable" else "render_failed"
                return MuseScoreVisualQaResult(status, reason)
            if completed is None:
                return MuseScoreVisualQaResult("render_failed", "renderer_execution_failed")
            if completed.returncode != 0:
                if _is_gui_session_unavailable(completed):
                    return MuseScoreVisualQaResult(
                        "musescore_gui_session_unavailable",
                        "musescore_gui_session_unavailable",
                    )
                return MuseScoreVisualQaResult("render_failed", "renderer_nonzero_exit")
            resolved_output = _resolved_output(output_path)
            if resolved_output is None:
                return MuseScoreVisualQaResult("render_failed", missing_reason)
            if output_path == pdf_path:
                pdf_path = resolved_output
            else:
                png_path = resolved_output
        return MuseScoreVisualQaResult(
            "completed",
            None,
            pdf_path=pdf_path,
            first_page_png_path=png_path,
        )

    def _resolve_renderer(self) -> str | None:
        if self.renderer_binary:
            return shutil.which(self.renderer_binary)
        for candidate in ("musescore", "mscore", "MuseScore"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    def _run(
        self,
        renderer: str,
        output_path: Path,
        musicxml_path: Path,
    ) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
        try:
            return (
                self.runner(
                    [renderer, "-o", str(output_path), str(musicxml_path)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                ),
                None,
            )
        except FileNotFoundError:
            return None, "renderer_unavailable"
        except subprocess.TimeoutExpired:
            return None, "renderer_timeout"


def _resolved_output(requested_path: Path) -> Path | None:
    if requested_path.is_file() and requested_path.stat().st_size > 0:
        return requested_path
    numbered_pages = sorted(requested_path.parent.glob(f"{requested_path.stem}-*.png"))
    for candidate in numbered_pages:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _is_gui_session_unavailable(completed: subprocess.CompletedProcess[str]) -> bool:
    output = f"{completed.stderr or ''}\n{completed.stdout or ''}".lower()
    return any(marker in output for marker in _GUI_SESSION_MARKERS)
