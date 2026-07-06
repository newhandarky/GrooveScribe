from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from scripts.redaction import find_unsafe_tokens
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from redaction import find_unsafe_tokens

TEMPLATE_PATH = Path("tests/manual_eval/manual_eval_template.csv")
DEFAULT_MANUAL_EVAL_DIR = Path("tests/manual_eval")
SCORE_FIELDS = (
    "kick_score",
    "snare_score",
    "hihat_score",
    "timing_score",
    "notation_readability_score",
    "overall_usability_score",
)


@dataclass(frozen=True)
class ManualEvalIssue:
    path: str
    row_number: int
    field: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate V1 manual eval CSV files.")
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--manual-eval-dir", type=Path, default=DEFAULT_MANUAL_EVAL_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = check_manual_eval_gate(args.manual_eval_dir, template_path=args.template)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


def check_manual_eval_gate(manual_eval_dir: Path, *, template_path: Path = TEMPLATE_PATH) -> dict:
    template_fields = _read_template_fields(template_path)
    issues: list[ManualEvalIssue] = []
    checked_rows = 0
    checked_files = 0
    for path in sorted(manual_eval_dir.glob("*.csv")):
        if path.name == template_path.name:
            continue
        checked_files += 1
        rows, fieldnames = _read_csv(path)
        if fieldnames != template_fields:
            issues.append(ManualEvalIssue(str(path), 1, "<header>", "header does not match manual_eval_template.csv"))
            continue
        for row_number, row in rows:
            if _is_blank_row(row):
                continue
            checked_rows += 1
            issues.extend(_validate_row(path, row_number, row))

    return {
        "schema_version": "1.0",
        "status": "passed" if not issues else "failed",
        "checked_files": checked_files,
        "checked_rows": checked_rows,
        "issues": [issue.__dict__ for issue in issues],
    }


def _read_template_fields(template_path: Path) -> list[str]:
    with template_path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _read_csv(path: Path) -> tuple[list[tuple[int, dict[str, str]]], list[str] | None]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(enumerate(reader, start=2)), reader.fieldnames


def _validate_row(path: Path, row_number: int, row: dict[str, str]) -> Iterable[ManualEvalIssue]:
    issues: list[ManualEvalIssue] = []
    blocked_reason = row.get("blocked_reason", "").strip()
    is_blocked = bool(blocked_reason)
    if is_blocked:
        for field in SCORE_FIELDS:
            if row.get(field, "").strip():
                issues.append(ManualEvalIssue(str(path), row_number, field, "blocked row must leave score field blank"))
    else:
        for field in ("baseline_report_ref", "artifact_ref"):
            if not row.get(field, "").strip():
                issues.append(ManualEvalIssue(str(path), row_number, field, "completed row requires ref"))
    for field, value in row.items():
        unsafe = find_unsafe_tokens(value)
        if unsafe:
            issues.append(
                ManualEvalIssue(str(path), row_number, field, f"unsafe diagnostic or local path token: {', '.join(unsafe)}")
            )
    return issues


def _is_blank_row(row: dict[str, str]) -> bool:
    return not any(value.strip() for value in row.values())


if __name__ == "__main__":
    raise SystemExit(main())
