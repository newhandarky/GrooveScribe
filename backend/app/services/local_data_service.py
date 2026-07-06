from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import TranscriptionJob


class LocalDataSummaryService:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings

    def summary(self, db: Session) -> dict:
        root = Path(self.settings.resolved_storage_root)
        jobs_root = root / "jobs"
        job_dirs = sorted(path.name for path in jobs_root.iterdir() if path.is_dir()) if jobs_root.exists() else []
        db_job_ids = set(db.scalars(select(TranscriptionJob.id)).all())
        orphan_dirs = [job_id for job_id in job_dirs if job_id not in db_job_ids]
        return {
            "schema_version": "1.0",
            "status": "dry_run",
            "dry_run": True,
            "execute_supported": False,
            "storage_root_name": root.name,
            "job_dir_count": len(job_dirs),
            "database_status": "readable",
            "database_job_count": len(db_job_ids),
            "orphan_job_dir_count": len(orphan_dirs),
            "warnings": [],
        }
