#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.errors import ApiErrorException  # noqa: E402
from app.services.internal_job_detail_service import InternalJobDetailService  # noqa: E402
from app.services.internal_snapshot_redaction import redact_pipeline_snapshot  # noqa: E402
from app.storage.local import LocalStorageAdapter  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings()
    database_url = args.database_url or settings.resolved_database_url
    storage_root = args.storage_root or settings.resolved_storage_root

    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    storage = LocalStorageAdapter(storage_root)
    service = InternalJobDetailService(storage=storage)

    try:
        with session_factory() as session:
            snapshot = service.get_pipeline_snapshot(session, args.job_id)
    except ApiErrorException as exc:
        print(
            json.dumps(
                {
                    "job_id": args.job_id,
                    "found": False,
                    "error": {
                        "code": str(exc.code),
                        "message": exc.message,
                        "details": exc.details,
                    },
                },
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return 1

    output = snapshot if args.raw else redact_pipeline_snapshot(snapshot)
    print(_to_json(output, pretty=args.pretty))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read an internal pipeline snapshot for a transcription job.",
    )
    parser.add_argument("--job-id", required=True, help="Transcription job id to inspect.")
    parser.add_argument("--database-url", help="Override backend database URL. Defaults to backend Settings.")
    parser.add_argument("--storage-root", help="Override storage root. Defaults to backend Settings.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--raw", action="store_true", help="Print unredacted internal debug fields.")
    return parser.parse_args(argv)


def _to_json(value: Any, *, pretty: bool) -> str:
    return json.dumps(_to_primitive(value), ensure_ascii=False, indent=2 if pretty else None)


def _to_primitive(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _to_primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_primitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_primitive(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
