from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import TranscriptionJob


_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely scan or remove orphaned local job artifact directories.")
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Delete only directories reported by the dry run.")
    return parser.parse_args()


def cleanup(config: argparse.Namespace) -> dict:
    storage_root = config.storage_root.expanduser().resolve()
    output_dir = config.output_dir.expanduser().resolve()
    if _inside_repo(storage_root) or _inside_repo(output_dir) or not _safe_database_url(config.database_url):
        return {"schema_version": "1.0", "status": "blocked", "reason_code": "cleanup_paths_must_be_outside_repo"}
    jobs_root = storage_root / "jobs"
    live_ids = _job_ids(config.database_url)
    candidates = sorted(
        entry.name
        for entry in jobs_root.iterdir()
        if jobs_root.is_dir() and entry.is_dir() and _safe_id(entry.name) and entry.name not in live_ids
    ) if jobs_root.is_dir() else []
    report = {
        "schema_version": "1.0",
        "status": "completed",
        "mode": "apply" if config.apply else "dry_run",
        "orphan_job_count": len(candidates),
        "deleted_job_count": 0,
        "backup_manifest_created": False,
    }
    if not config.apply or not candidates:
        return report
    output_dir.mkdir(parents=True, exist_ok=True)
    backup = {"schema_version": "1.0", "artifact_kind": "orphan_job_directories", "job_ids": candidates}
    (output_dir / "cleanup_backup_manifest.json").write_text(json.dumps(backup, indent=2) + "\n", encoding="utf-8")
    for job_id in candidates:
        target = (jobs_root / job_id).resolve()
        if target.parent != jobs_root.resolve():
            continue
        shutil.rmtree(target)
        report["deleted_job_count"] += 1
    report["backup_manifest_created"] = True
    (output_dir / "cleanup_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _job_ids(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    with Session(engine) as db:
        return {str(value) for value in db.scalars(select(TranscriptionJob.id))}


def _safe_database_url(value: str) -> bool:
    prefixes = ("sqlite:///", "sqlite+pysqlite:///")
    prefix = next((item for item in prefixes if value.startswith(item)), None)
    if prefix is None:
        return False
    path = Path(value.removeprefix(prefix))
    return path.is_absolute() and not _inside_repo(path)


def _inside_repo(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == _ROOT or _ROOT in resolved.parents


def _safe_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)


if __name__ == "__main__":
    result = cleanup(parse_args())
    print(json.dumps({"status": result["status"], "mode": result.get("mode")}, ensure_ascii=False))
