from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

_SENSITIVE_TEXT_TOKENS = (
    "traceback",
    "stdout",
    "stderr",
    "command_template",
    "raw command",
)

FIELDNAMES = [
    "date",
    "fixture_name",
    "runtime_mode",
    "pipeline_version",
    "runtime_version",
    "baseline_report_ref",
    "artifact_ref",
    "source_separator",
    "drum_transcriber",
    "raw_event_count",
    "processed_event_count",
    "raw_note_histogram",
    "processed_drum_counts",
    "quality_flags",
    "warnings",
    "kick_score",
    "snare_score",
    "hihat_score",
    "timing_score",
    "notation_readability_score",
    "overall_usability_score",
    "confidence_label",
    "major_errors",
    "blocked_reason",
    "notes",
    "reviewer",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a manual eval CSV row from a baseline.json report.")
    parser.add_argument("baseline_report", type=Path)
    parser.add_argument("--reviewer", default="Codex")
    parser.add_argument("--runtime-mode", default="true_ai")
    parser.add_argument("--pipeline-version", default="local-first-v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.baseline_report.read_text(encoding="utf-8"))
    row = generate_manual_eval_row(
        payload,
        baseline_report_path=args.baseline_report,
        reviewer=args.reviewer,
        runtime_mode=args.runtime_mode,
        pipeline_version=args.pipeline_version,
    )
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDNAMES, lineterminator="\n")
    writer.writerow(row)
    return 0


def generate_manual_eval_row(
    baseline: dict[str, Any],
    *,
    baseline_report_path: Path,
    reviewer: str,
    runtime_mode: str,
    pipeline_version: str,
) -> dict[str, str]:
    status = str(baseline.get("status") or "unknown")
    checked_at = str(baseline.get("checked_at") or "")
    run_ref = _baseline_ref(baseline, baseline_report_path)
    runtime = _dict(baseline.get("runtime"))
    quality = _dict(baseline.get("quality"))
    inspection = _dict(baseline.get("inspection"))
    drum_events = _dict(inspection.get("drum_events"))

    row = {field: "" for field in FIELDNAMES}
    row.update(
        {
            "date": checked_at[:10],
            "fixture_name": _redact_ref(str(baseline.get("input_fixture") or "")),
            "runtime_mode": runtime_mode,
            "pipeline_version": pipeline_version,
            "runtime_version": _runtime_version(runtime),
            "baseline_report_ref": run_ref,
            "artifact_ref": _artifact_ref(baseline),
            "source_separator": _source_separator(baseline),
            "drum_transcriber": _drum_transcriber(runtime),
            "raw_event_count": _string_or_empty(quality.get("raw_event_count")),
            "processed_event_count": _string_or_empty(quality.get("processed_event_count")),
            "raw_note_histogram": _json_cell(quality.get("raw_note_histogram") or drum_events.get("raw_note_histogram")),
            "processed_drum_counts": _json_cell(
                quality.get("processed_drum_counts") or drum_events.get("processed_drum_counts")
            ),
            "quality_flags": _join_codes(quality.get("quality_flags")),
            "warnings": _join_codes(quality.get("warnings") or _pipeline_warnings(baseline)),
            "blocked_reason": _blocked_reason(baseline) if status == "blocked" else "",
            "notes": _notes(status, baseline),
            "reviewer": reviewer,
        }
    )
    return row


def _runtime_version(runtime: dict[str, Any]) -> str:
    pieces = [
        _string_or_empty(runtime.get("python_version")),
        f"demucs-{_string_or_empty(runtime.get('demucs_device'))}",
        f"adtof-{_string_or_empty(runtime.get('adtof_device'))}-threshold-{_string_or_empty(runtime.get('adtof_threshold'))}",
    ]
    return "; ".join(piece for piece in pieces if piece and not piece.endswith("-"))


def _source_separator(baseline: dict[str, Any]) -> str:
    runtime = _dict(baseline.get("runtime"))
    return f"demucs-{_string_or_empty(runtime.get('demucs_device'))}".rstrip("-")


def _drum_transcriber(runtime: dict[str, Any]) -> str:
    device = _string_or_empty(runtime.get("adtof_device"))
    threshold = _string_or_empty(runtime.get("adtof_threshold"))
    return f"adtof-{device}-threshold-{threshold}".strip("-")


def _artifact_ref(baseline: dict[str, Any]) -> str:
    output_dir_name = str(baseline.get("output_dir_name") or "")
    return f"external:{_slug(output_dir_name)}" if output_dir_name else ""


def _baseline_ref(baseline: dict[str, Any], path: Path) -> str:
    explicit = str(baseline.get("baseline_ref") or "")
    if explicit:
        return _redact_ref(explicit)
    parent = path.parent.name or path.stem
    return f"baseline:{_slug(parent)}"


def _pipeline_warnings(baseline: dict[str, Any]) -> list[str]:
    return [str(item) for item in _list(_dict(baseline.get("pipeline")).get("warnings"))]


def _blocked_reason(baseline: dict[str, Any]) -> str:
    explicit = str(baseline.get("blocked_reason") or "")
    if explicit:
        return _redact_ref(explicit)
    status_code = _string_or_empty(_dict(baseline.get("preflight")).get("adtof_status_code"))
    return f"ADTOF status_code={status_code}" if status_code else "true-AI runtime blocked"


def _notes(status: str, baseline: dict[str, Any]) -> str:
    if status == "blocked":
        return "Baseline blocked; scores intentionally left blank."
    exports = _dict(baseline.get("exports"))
    pdf = _dict(exports.get("pdf"))
    return f"Baseline {status}; PDF {pdf.get('status', 'unknown')} and optional."


def _redact_ref(value: str) -> str:
    redacted = re.sub(r"/Users/[^\s,\"']+", "<local-path>", value)
    redacted = re.sub(r"/private/tmp/[^\s,\"']+", "<local-path>", redacted)
    redacted = re.sub(r"/tmp/[^\s,\"']+", "<local-path>", redacted)
    redacted = re.sub(r"/private/var/[^\s,\"']+", "<local-path>", redacted)
    redacted = re.sub(r"/var/folders/[^\s,\"']+", "<local-path>", redacted)
    if any(token in redacted.lower() for token in _SENSITIVE_TEXT_TOKENS):
        return "<redacted>"
    return redacted


def _slug(value: str) -> str:
    value = _redact_ref(value)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug or "unknown"


def _join_codes(value: object) -> str:
    codes = [_redact_ref(str(item)) for item in _list(value)]
    return "; ".join(code for code in codes if code not in {"<redacted>", "<local-path>"})


def _json_cell(value: object) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)


def _string_or_empty(value: object) -> str:
    return "" if value is None else str(value)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
