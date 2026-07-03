from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect local GrooveScribe storage for cleanup candidates.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage/local"))
    parser.add_argument("--database", type=Path, default=Path("storage/local/groovescribe.db"))
    parser.add_argument("--execute", action="store_true", help="Reserved for a later slice; current tool is dry-run only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.execute:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "execute_refused": True,
                    "message": "cleanup_storage.py is dry-run only in this slice",
                },
                indent=2,
            )
        )
        return 2
    payload = inspect_storage(args.storage_root, args.database)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def inspect_storage(storage_root: Path, database_path: Path) -> dict:
    root = storage_root.expanduser().resolve()
    jobs_root = root / "jobs"
    job_dirs = sorted(path.name for path in jobs_root.iterdir() if path.is_dir()) if jobs_root.exists() else []
    db_job_ids, database_status = _read_db_job_ids(database_path)
    orphan_job_dirs = [job_id for job_id in job_dirs if db_job_ids is not None and job_id not in db_job_ids]
    return {
        "schema_version": "1.0",
        "status": "dry_run",
        "dry_run": True,
        "execute_supported": False,
        "execute_refused": False,
        "storage_root_name": root.name,
        "job_dir_count": len(job_dirs),
        "job_dirs": job_dirs,
        "database_found": database_path.expanduser().exists(),
        "database_status": database_status,
        "database_job_count": len(db_job_ids) if db_job_ids is not None else None,
        "orphan_job_dirs": orphan_job_dirs,
        "deleted": [],
    }


def _read_db_job_ids(database_path: Path) -> tuple[set[str] | None, str]:
    path = database_path.expanduser()
    if not path.exists():
        return None, "missing"
    try:
        with sqlite3.connect(path) as connection:
            rows = connection.execute("select id from transcription_jobs").fetchall()
    except sqlite3.Error:
        return None, "unreadable"
    return {str(row[0]) for row in rows}, "readable"


if __name__ == "__main__":
    raise SystemExit(main())
