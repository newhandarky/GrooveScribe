from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from ai_pipeline.notation.errors import PdfExportFailedError, PdfRendererNotAvailableError
from ai_pipeline.notation.types import PdfExportResult

CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class MuseScorePdfExporter:
    def __init__(
        self,
        renderer_binary: str | None = None,
        timeout_seconds: int = 120,
        runner: CompletedProcessRunner = subprocess.run,
    ) -> None:
        self.renderer_binary = renderer_binary
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def export(self, musicxml_path: Path, output_dir: Path) -> PdfExportResult:
        if not musicxml_path.exists():
            raise PdfExportFailedError(f"MusicXML does not exist: {musicxml_path}")

        renderer = self._resolve_renderer()
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / "score.pdf"
        command = [renderer, "-o", str(pdf_path), str(musicxml_path)]

        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PdfRendererNotAvailableError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise PdfExportFailedError(str(exc)) from exc

        pdf_created = pdf_path.exists() and pdf_path.stat().st_size > 0
        if completed.returncode != 0 and pdf_created:
            stderr = (completed.stderr or "").strip()
            message = stderr or f"PDF renderer exited with code {completed.returncode} after creating output"
            return PdfExportResult(
                pdf_path=pdf_path,
                renderer=renderer,
                warnings=(f"renderer_nonzero_exit: {message}",),
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            message = stderr or f"PDF renderer failed with exit code {completed.returncode}"
            raise PdfExportFailedError(message)
        if not pdf_created:
            raise PdfExportFailedError(f"PDF renderer did not create output: {pdf_path}")

        return PdfExportResult(pdf_path=pdf_path, renderer=renderer)

    def _resolve_renderer(self) -> str:
        if self.renderer_binary:
            resolved = shutil.which(self.renderer_binary)
            if resolved:
                return resolved
            raise PdfRendererNotAvailableError(f"renderer not found: {self.renderer_binary}")

        for candidate in ("musescore", "mscore", "MuseScore"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        raise PdfRendererNotAvailableError("MuseScore CLI was not found in PATH")
