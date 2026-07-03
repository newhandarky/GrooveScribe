from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def validate_musicxml_artifact(musicxml_path: Path) -> dict:
    if not musicxml_path.exists() or not musicxml_path.is_file():
        return {
            "available": False,
            "parseable": False,
            "error_code": "musicxml_unavailable",
            "warnings": ["musicxml_unavailable"],
        }
    if musicxml_path.stat().st_size <= 0:
        return {
            "available": True,
            "parseable": False,
            "error_code": "musicxml_empty",
            "warnings": ["musicxml_empty"],
        }
    try:
        root = ET.parse(musicxml_path).getroot()
    except ET.ParseError:
        return {
            "available": True,
            "parseable": False,
            "error_code": "musicxml_unparseable",
            "warnings": ["musicxml_unparseable"],
        }

    warnings: list[str] = []
    if root.tag != "score-partwise":
        warnings.append("musicxml_root_unexpected")
    if not root.get("version"):
        warnings.append("musicxml_version_missing")
    if root.find("./part/measure") is None:
        warnings.append("musicxml_measure_missing")
    return {
        "available": True,
        "parseable": True,
        "error_code": warnings[0] if warnings else None,
        "warnings": warnings,
    }


def validate_pdf_artifact(pdf_path: Path | None) -> dict:
    if pdf_path is None or not pdf_path.exists() or not pdf_path.is_file():
        return {
            "available": False,
            "optional": True,
            "openable": None,
            "error_code": "pdf_unavailable",
            "warnings": ["pdf_optional_unavailable"],
        }
    if pdf_path.stat().st_size <= 0:
        return {
            "available": True,
            "optional": True,
            "openable": False,
            "error_code": "pdf_empty",
            "warnings": ["pdf_empty"],
        }
    try:
        with pdf_path.open("rb") as handle:
            header = handle.read(4)
    except OSError:
        return {
            "available": True,
            "optional": True,
            "openable": False,
            "error_code": "pdf_unreadable",
            "warnings": ["pdf_unreadable"],
        }
    openable = header == b"%PDF"
    return {
        "available": True,
        "optional": True,
        "openable": openable,
        "error_code": None if openable else "pdf_header_invalid",
        "warnings": [] if openable else ["pdf_header_invalid"],
    }


def validate_score_artifacts(musicxml_path: Path, pdf_path: Path | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "musicxml": validate_musicxml_artifact(musicxml_path),
        "pdf": validate_pdf_artifact(pdf_path),
    }
