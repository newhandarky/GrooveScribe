from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-review-packet")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a redacted V1 review packet outside the repo.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--database", type=Path, default=Path("storage/local/groovescribe.db"))
    parser.add_argument("--storage-root", type=Path, default=Path("storage/local"))
    parser.add_argument("--zip", action="store_true", help="Also write review_packet.zip.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if _inside_repo(args.output_dir):
        print(_failure_json("output_dir_must_be_outside_repo"))
        return 2
    try:
        return _export(args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must never print tracebacks.
        print(_failure_json(_safe_error_code(exc)))
        return 1


def _export(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import sessionmaker

    from app.core.config import Settings
    from app.core.errors import ApiErrorException
    from app.services.review_packet_service import ReviewPacketService
    from app.storage.local import LocalStorageAdapter

    try:
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        settings = Settings(
            database_url=f"sqlite+pysqlite:///{_resolve_path(args.database)}",
            storage_root=str(_resolve_path(args.storage_root)),
        )
        storage = LocalStorageAdapter(settings.resolved_storage_root)
        engine = create_engine(settings.resolved_database_url, pool_pre_ping=True)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        service = ReviewPacketService(settings=settings, storage=storage)

        with session_factory() as db:
            packet = service.build_packet(db, job_id=args.job_id)
            if not _packet_redaction_passed(packet):
                print(_failure_json("review_packet_redaction_failed"))
                return 1
            notes = service.build_notes_markdown(packet)
            zip_written = False
            (output_dir / "review_packet.json").write_text(
                json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (output_dir / "review_notes.md").write_text(notes + "\n", encoding="utf-8")
            if args.zip:
                packet_zip = service.build_zip(db, job_id=args.job_id)
                (output_dir / packet_zip.filename).write_bytes(packet_zip.content)
                zip_written = True
    except ApiErrorException as exc:
        print(_failure_json(exc.code))
        return 1
    except (SQLAlchemyError, OSError, ValueError):
        print(_failure_json("review_packet_export_failed"))
        return 1

    summary = {
        "schema_version": "1.0",
        "status": "exported",
        "job_id": args.job_id,
        "output_dir": output_dir.name,
        "files": ["review_packet.json", "review_notes.md"] + (["review_packet.zip"] if zip_written else []),
    }
    if find_unsafe_tokens(json.dumps(summary, ensure_ascii=False)):
        print(_failure_json("unsafe_output"))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _packet_redaction_passed(packet: dict[str, Any]) -> bool:
    redaction = packet.get("redaction")
    return isinstance(redaction, dict) and redaction.get("status") == "passed"


def _resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _inside_repo(path: Path) -> bool:
    resolved = _resolve_path(path)
    try:
        resolved.relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def find_unsafe_tokens(value: Any) -> list[str]:
    text = str(value)
    lowered = text.lower()
    found = [token for token in UNSAFE_TOKENS if token in text or token.lower() in lowered]
    return sorted(set(found))


def _failure_json(error: str) -> str:
    payload = {"schema_version": "1.0", "status": "failed", "error": _safe_error_text(error)}
    return json.dumps(payload, ensure_ascii=False)


def _safe_error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return "review_packet_export_failed"


def _safe_error_text(value: object) -> str:
    text = str(value) if value is not None else "review_packet_export_failed"
    return "review_packet_export_failed" if find_unsafe_tokens(text) else text


if __name__ == "__main__":
    raise SystemExit(main())
