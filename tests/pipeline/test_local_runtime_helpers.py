from pathlib import Path

from scripts.cleanup_storage import inspect_storage
from scripts.prepare_adtof_verify_input import main as prepare_adtof_main


def test_cleanup_storage_dry_run_lists_orphan_job_dirs(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    (storage_root / "jobs" / "orphan-job").mkdir(parents=True)

    report = inspect_storage(storage_root, tmp_path / "missing.db")

    assert report["dry_run"] is True
    assert report["status"] == "dry_run"
    assert report["execute_supported"] is False
    assert report["execute_refused"] is False
    assert report["storage_root_name"] == "storage"
    assert report["job_dir_count"] == 1
    assert report["job_dirs"] == ["orphan-job"]
    assert report["database_found"] is False
    assert report["database_status"] == "missing"
    assert report["deleted"] == []


def test_prepare_adtof_verify_input_dry_run_does_not_create_artifacts(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input.wav"
    normalized_dir = tmp_path / "normalized"
    stems_dir = tmp_path / "stems"
    source.write_bytes(b"not real audio")
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_adtof_verify_input.py",
            "--input",
            str(source),
            "--normalized-dir",
            str(normalized_dir),
            "--stems-dir",
            str(stems_dir),
            "--dry-run",
        ],
    )

    assert prepare_adtof_main() == 0
    assert not normalized_dir.exists()
    assert not stems_dir.exists()
