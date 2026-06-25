from pathlib import Path

from app.storage.local import LocalStorageAdapter


def test_put_bytes_open_reader_exists_and_stat(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(tmp_path)
    ref = adapter.put_bytes(
        b"hello",
        "jobs/job-1/logs/pipeline.json",
        "application/json",
    )

    assert ref.storage_key == "jobs/job-1/logs/pipeline.json"
    assert ref.content_type == "application/json"
    assert ref.file_size_bytes == 5
    assert ref.checksum is not None
    assert adapter.exists("jobs/job-1/logs/pipeline.json") is True

    stat = adapter.stat("jobs/job-1/logs/pipeline.json")
    assert stat.file_size_bytes == 5
    assert stat.checksum == ref.checksum

    with adapter.open_reader("jobs/job-1/logs/pipeline.json") as reader:
        assert reader.read() == b"hello"


def test_put_file_copies_to_storage_root(tmp_path: Path) -> None:
    source = tmp_path / "source.mid"
    source.write_bytes(b"midi")
    adapter = LocalStorageAdapter(tmp_path / "storage")

    ref = adapter.put_file(source, "jobs/job-1/midi/processed_drum.mid", "audio/midi")

    assert ref.file_size_bytes == 4
    assert (tmp_path / "storage" / "jobs" / "job-1" / "midi" / "processed_drum.mid").read_bytes() == b"midi"


def test_unsafe_key_is_rejected(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(tmp_path)

    for key in ("../secret.txt", "/tmp/secret.txt", "jobs" + chr(92) + "secret.txt"):
        try:
            adapter.put_bytes(b"x", key, "text/plain")
        except Exception as exc:
            assert getattr(exc, "code") == "PATH_TRAVERSAL_REJECTED"
        else:
            raise AssertionError(f"expected PATH_TRAVERSAL_REJECTED for {key}")


def test_download_url_does_not_expose_absolute_path(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(tmp_path)
    download_url = adapter.create_download_url("jobs/job-1/exports/score.pdf", expires_in_seconds=60)

    assert download_url.url == "/api/v1/storage/local/jobs/job-1/exports/score.pdf"
    assert str(tmp_path) not in download_url.url
    assert download_url.expires_in_seconds == 60


def test_missing_artifact_raises_domain_error(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(tmp_path)

    try:
        adapter.open_reader("jobs/job-1/missing.wav")
    except Exception as exc:
        assert getattr(exc, "code") == "ARTIFACT_NOT_FOUND"
    else:
        raise AssertionError("expected ARTIFACT_NOT_FOUND")
