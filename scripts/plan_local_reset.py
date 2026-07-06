from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan a local GrooveScribe reset without deleting files.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage/local"))
    parser.add_argument("--database", type=Path, default=Path("storage/local/groovescribe.db"))
    parser.add_argument("--execute", action="store_true", help="Reserved; this tool is dry-run only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = plan_local_reset(args.storage_root, args.database, execute=args.execute)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.execute else 0


def plan_local_reset(storage_root: Path, database_path: Path, *, execute: bool = False) -> dict:
    if execute:
        return {
            "schema_version": "1.0",
            "status": "refused",
            "dry_run": True,
            "execute_supported": False,
            "execute_refused": True,
            "message": "plan_local_reset.py is dry-run only",
        }
    root = storage_root.expanduser()
    db = database_path.expanduser()
    return {
        "schema_version": "1.0",
        "status": "dry_run",
        "dry_run": True,
        "execute_supported": False,
        "execute_refused": False,
        "targets": {
            "storage_root": {
                "path_ref": _safe_path_ref(root),
                "exists": root.exists(),
            },
            "jobs_root": {
                "path_ref": _safe_path_ref(root / "jobs"),
                "exists": (root / "jobs").exists(),
            },
            "database": {
                "path_ref": _safe_path_ref(db),
                "exists": db.exists(),
            },
        },
        "would_delete": [],
        "message": "Dry-run only; no files were deleted.",
    }


def _safe_path_ref(path: Path) -> str:
    text = path.as_posix()
    if path.is_absolute():
        return path.name
    return text


if __name__ == "__main__":
    raise SystemExit(main())
