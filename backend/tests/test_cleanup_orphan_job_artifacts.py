from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AudioFile, TranscriptionJob
from app.models.enums import JobStatus, PipelineStage


def _script():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("cleanup_orphans", root / "scripts" / "cleanup_orphan_job_artifacts.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _database(tmp_path: Path) -> str:
    path = tmp_path / "outside.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            TranscriptionJob(
                id="known",
                audio_file=AudioFile(
                    id="audio-known", original_filename="known.wav", content_type="audio/wav", file_size_bytes=1,
                    original_storage_key="jobs/known/original/known.wav",
                ),
                status=JobStatus.COMPLETED,
                stage=PipelineStage.COMPLETED,
            )
        )
        db.commit()
    return f"sqlite+pysqlite:///{path}"


def test_cleanup_is_dry_run_by_default_then_applies_only_orphan_job_dirs(tmp_path: Path) -> None:
    script = _script()
    storage = tmp_path / "storage"
    (storage / "jobs" / "known").mkdir(parents=True)
    (storage / "jobs" / "orphan").mkdir(parents=True)
    output = tmp_path / "reports"
    config = type("Config", (), {"storage_root": storage, "database_url": _database(tmp_path), "output_dir": output, "apply": False})()

    assert script.cleanup(config) == {"schema_version": "1.0", "status": "completed", "mode": "dry_run", "orphan_job_count": 1, "deleted_job_count": 0, "backup_manifest_created": False}
    assert (storage / "jobs" / "orphan").exists()
    config.apply = True
    applied = script.cleanup(config)
    assert applied["deleted_job_count"] == 1
    assert not (storage / "jobs" / "orphan").exists()
    assert (storage / "jobs" / "known").exists()
    assert (output / "cleanup_backup_manifest.json").exists()


def test_cleanup_rejects_repo_local_storage_or_report_paths(tmp_path: Path) -> None:
    script = _script()
    config = type("Config", (), {"storage_root": Path(__file__).resolve().parents[2] / "storage", "database_url": _database(tmp_path), "output_dir": tmp_path / "reports", "apply": False})()

    assert script.cleanup(config)["reason_code"] == "cleanup_paths_must_be_outside_repo"
