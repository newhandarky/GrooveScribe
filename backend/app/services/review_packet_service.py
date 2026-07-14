from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.models import ExportFile, TranscriptionJob
from app.models.enums import ExportFileStatus, ExportFileType
from app.services.result_service import ResultService
from app.storage import ArtifactType, build_job_artifact_key
from app.storage.base import StorageAdapter
from app.storage.errors import ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError

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
PUBLIC_PACKET_BLOCKED_KEYS = {"storage_key", "pipeline_log"}

ZIP_FILENAMES = {
    ExportFileType.MIDI: "drums.mid",
    ExportFileType.MUSICXML: "score.musicxml",
    ExportFileType.PDF: "score.pdf",
}


@dataclass(frozen=True)
class ReviewPacketZip:
    content: bytes
    filename: str = "review_packet.zip"
    content_type: str = "application/zip"


class ReviewPacketService:
    def __init__(self, *, settings: Settings, storage: StorageAdapter) -> None:
        self.settings = settings
        self.storage = storage
        self.result_service = ResultService(settings=settings, storage=storage)

    def build_packet(self, db: Session, *, job_id: str) -> dict:
        job = self.result_service.get_completed_result(db, job_id)
        packet = self._build_packet_from_job(job)
        packet["redaction"] = {"status": "passed", "unsafe_token_count": 0}
        _assert_public_safe_packet(packet)
        return packet

    def build_notes_markdown(self, packet: dict) -> str:
        quality = packet.get("quality") or {}
        validation = packet.get("validation") or {}
        pipeline_config = packet.get("pipeline_config") or {}
        lines = [
            "# GrooveScribe Review Packet",
            "",
            f"- Job: `{packet['job'].get('job_id')}`",
            f"- Title: `{packet['job'].get('title') or 'untitled'}`",
            f"- Runtime mode: `{packet['manual_eval_seed'].get('runtime_mode', 'unknown')}`",
            f"- Pipeline config: `{pipeline_config.get('mode', 'unknown')}`",
            f"- Artifact ref: `{packet['manual_eval_seed'].get('artifact_ref', '')}`",
            "",
            "## Exports",
            "",
        ]
        for export in packet.get("exports", []):
            optional = " optional" if export.get("optional") else ""
            lines.append(f"- `{export.get('type')}`: `{export.get('status')}`{optional}")
        lines.extend(
            [
                "",
                "## Quality",
                "",
                f"- Raw events: `{quality.get('raw_event_count')}`",
                f"- Processed events: `{quality.get('processed_event_count')}`",
                f"- Quality flags: `{', '.join(quality.get('quality_flags') or []) or 'none'}`",
                "",
                "## Validation",
                "",
                f"- MusicXML: `{(validation.get('musicxml') or {}).get('status', 'not_reported')}`",
                f"- PDF: `{(validation.get('pdf') or {}).get('status', 'not_reported')}`",
                f"- Visual QA: `{(validation.get('visual_qa') or {}).get('status', 'not_reported')}`",
                "",
                "## Automated delivery checks",
                "",
            ]
        )
        for item in packet.get("review_checklist", []):
            lines.append(f"- [ ] {item.get('label')}: {item.get('detail')}")
        lines.extend(
            [
                "",
                "## Delivery status",
                "",
                "`quality.performance_gate` is the authoritative automated delivery decision. Only `performance_ready` is marked as directly playable.",
            ]
        )
        rendered = "\n".join(lines)
        unsafe = find_unsafe_tokens(rendered)
        if unsafe:
            _raise_redaction_failed()
        return rendered

    def build_zip(self, db: Session, *, job_id: str) -> ReviewPacketZip:
        packet = self.build_packet(db, job_id=job_id)
        notes = self.build_notes_markdown(packet)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("review_packet.json", json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("review_notes.md", notes + "\n")
            job = self.result_service.get_completed_result(db, job_id)
            for export in _sorted_exports(job.export_files):
                filename = ZIP_FILENAMES.get(export.type)
                if filename is None or not self._export_available(export):
                    continue
                try:
                    with self.storage.open_reader(export.storage_key) as reader:
                        archive.writestr(filename, reader.read())
                except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError):
                    continue
            chart_events_key = build_job_artifact_key(job.id, ArtifactType.CHART_EVENTS)
            try:
                with self.storage.open_reader(chart_events_key) as reader:
                    archive.writestr("chart_events.json", reader.read())
            except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError):
                pass
            preview_key = build_job_artifact_key(job.id, ArtifactType.VISUAL_PREVIEW)
            try:
                with self.storage.open_reader(preview_key) as reader:
                    archive.writestr("score_preview.png", reader.read())
            except (ArtifactInvalidError, ArtifactNotFoundError, StorageReadFailedError):
                pass
        return ReviewPacketZip(content=buffer.getvalue())

    def _build_packet_from_job(self, job: TranscriptionJob) -> dict:
        pipeline = self.result_service.pipeline_summary(job) or {}
        quality = pipeline.get("quality")
        validation = _validation_statuses(pipeline.get("validation"))
        exports = [self._export_summary(job.id, export) for export in _sorted_exports(job.export_files)]
        warnings = sorted(set((pipeline.get("warnings") or []) + (quality or {}).get("warnings", [])))
        flags = (quality or {}).get("quality_flags", [])
        packet = {
            "schema_version": "1.0",
            "status": "ready",
            "job": {
                "job_id": job.id,
                "title": _safe_text(job.title),
                "status": job.status.value,
                "stage": job.stage.value,
                "created_at": _iso(job.created_at),
                "completed_at": _iso(job.completed_at),
            },
            "audio": {
                "file_name": _safe_filename(job.audio_file.original_filename),
                "content_type": job.audio_file.content_type,
                "file_size_bytes": job.audio_file.file_size_bytes,
                "duration_seconds": job.audio_file.duration_seconds,
                "sample_rate": job.audio_file.sample_rate,
                "channels": job.audio_file.channels,
            },
            "exports": exports,
            "pipeline_config": pipeline.get("config"),
            "quality": quality,
            "validation": validation,
            "audio_review": self.result_service.review_timeline(job),
            "review_checklist": _review_checklist(flags, warnings, validation, exports),
            "manual_eval_seed": _manual_eval_seed(job, pipeline, quality, warnings),
            "redaction": {"status": "not_checked", "unsafe_token_count": 0},
        }
        return _sanitize_object(packet)

    def _export_summary(self, job_id: str, export: ExportFile) -> dict:
        storage_available = export.status == ExportFileStatus.AVAILABLE and self._export_available(export)
        status = export.status.value if storage_available else "unavailable" if export.status == ExportFileStatus.AVAILABLE else export.status.value
        return {
            "type": export.type.value,
            "status": status,
            "optional": export.type == ExportFileType.PDF,
            "content_type": export.content_type,
            "file_size_bytes": export.file_size_bytes if storage_available else None,
            "download_url": self.result_service.download_url(job_id, export.type.value) if storage_available else None,
            "included_in_zip": storage_available,
        }

    def _export_available(self, export: ExportFile) -> bool:
        try:
            return self.storage.exists(export.storage_key)
        except Exception:
            return False


def find_unsafe_tokens(value: Any) -> list[str]:
    text = str(value)
    lowered = text.lower()
    found = [token for token in UNSAFE_TOKENS if token in text or token.lower() in lowered]
    return sorted(set(found))


def _assert_public_safe_packet(packet: dict) -> None:
    unsafe = find_unsafe_tokens(json.dumps(packet, ensure_ascii=False))
    if unsafe:
        _raise_redaction_failed()


def _raise_redaction_failed() -> None:
    raise ApiErrorException(
        ErrorCode.INTERNAL_SERVER_ERROR,
        message="Review packet redaction failed.",
        retriable=False,
    )


def _sorted_exports(exports: list[ExportFile]) -> list[ExportFile]:
    return sorted(exports, key=lambda item: item.type.value)


def _validation_statuses(validation: dict | None) -> dict | None:
    if validation is None:
        return None
    musicxml = validation.get("musicxml") or {}
    pdf = validation.get("pdf") or {}
    result = {
        "musicxml": {
            **musicxml,
            "status": "parseable" if musicxml.get("parseable") else "unavailable" if not musicxml.get("available") else "needs_review",
        },
        "pdf": {
            **pdf,
            "status": "openable" if pdf.get("openable") else "optional_unavailable" if pdf.get("optional") else "unavailable",
        },
    }
    visual_qa = validation.get("visual_qa")
    if isinstance(visual_qa, dict):
        status = str(visual_qa.get("status") or "not_requested")
        if status not in {
            "completed",
            "musescore_gui_session_unavailable",
            "renderer_unavailable",
            "render_failed",
            "not_requested",
        }:
            status = "not_requested"
        result["visual_qa"] = {
            "status": status,
            "reason_code": str(visual_qa.get("reason_code") or "") or None,
            "pdf_available": bool(visual_qa.get("pdf_available")),
            "first_page_png_available": bool(visual_qa.get("first_page_png_available")),
        }
    return result


def _manual_eval_seed(job: TranscriptionJob, pipeline: dict, quality: dict | None, warnings: list[str]) -> dict:
    quality = quality or {}
    return {
        "date": "",
        "fixture_name": _safe_filename(job.audio_file.original_filename),
        "runtime_mode": pipeline.get("mode", "unknown"),
        "pipeline_config": pipeline.get("config", {}),
        "pipeline_version": job.pipeline_version,
        "runtime_version": "",
        "baseline_report_ref": f"review:{job.id}",
        "artifact_ref": f"review:{job.id}",
        "source_separator": _safe_text(job.source_separator),
        "drum_transcriber": _safe_text(job.drum_transcriber),
        "raw_event_count": quality.get("raw_event_count"),
        "processed_event_count": quality.get("processed_event_count"),
        "raw_note_histogram": quality.get("raw_note_histogram", {}),
        "processed_drum_counts": quality.get("processed_drum_counts", {}),
        "quality_flags": quality.get("quality_flags", []),
        "warnings": warnings,
        "blocked_reason": "",
    }


def _review_checklist(flags: list[str], warnings: list[str], validation: dict | None, exports: list[dict]) -> list[dict]:
    items = [
        {"code": "automated_quality_gate", "label": "自動品質 gate", "detail": "只在節奏、可演奏性與音訊對齊驗證通過時交付可直接演奏版本。"},
        {"code": "musicxml_validation", "label": "MusicXML", "detail": "系統已驗證 MusicXML 與 Performance MIDI 的可讀取性。"},
    ]
    if flags:
        items.append({"code": "review_quality_flags", "label": "Quality flags", "detail": ", ".join(flags)})
    if warnings:
        items.append({"code": "review_warnings", "label": "Warnings", "detail": ", ".join(warnings)})
    pdf = next((item for item in exports if item.get("type") == "pdf"), None)
    if pdf is None or pdf.get("status") != "available":
        items.append({"code": "pdf_optional", "label": "PDF optional", "detail": "PDF 不影響 MIDI / MusicXML 的自動演奏交付。"})
    if validation is None:
        items.append({"code": "validation_missing", "label": "Validation", "detail": "舊資料缺少自動驗證摘要，因此不可標示為可直接演奏。"})
    return items


def _sanitize_object(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _safe_dict_key(key)
            if safe_key is None or safe_key in sanitized:
                continue
            sanitized[safe_key] = _sanitize_object(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_object(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _safe_dict_key(value: object) -> str | None:
    key = str(value)
    if key in PUBLIC_PACKET_BLOCKED_KEYS or find_unsafe_tokens(key):
        return None
    safe_key = _safe_text(key)
    return safe_key if safe_key and safe_key != "[redacted]" else None


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return "[redacted]" if find_unsafe_tokens(text) else text


def _safe_filename(value: str) -> str:
    name = value.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]
    return _safe_text(name) or "audio"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
