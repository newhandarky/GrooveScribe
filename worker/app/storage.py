from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class StorageKeyError(ValueError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    content_type: str
    file_size_bytes: int
    checksum: str


def sanitize_filename(filename: str) -> str:
    cleaned = _SAFE_FILENAME_PATTERN.sub("_", filename.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.replace("_.", ".").strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise StorageKeyError(f"unsafe filename: {filename}")
    return cleaned[:255]


def sanitize_storage_key(storage_key: str) -> str:
    if not storage_key or storage_key.strip() != storage_key:
        raise StorageKeyError("storage key is empty or has surrounding whitespace")
    if chr(92) in storage_key:
        raise StorageKeyError("backslashes are not allowed in storage keys")
    path = PurePosixPath(storage_key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StorageKeyError(f"unsafe storage key: {storage_key}")
    return str(path)


def job_artifact_key(job_id: str, suffix: str) -> str:
    return sanitize_storage_key(f"jobs/{sanitize_filename(job_id)}/{suffix}")


class LocalWorkerStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, storage_key: str, content: bytes, content_type: str) -> StoredArtifact:
        safe_key = sanitize_storage_key(storage_key)
        target = self._resolve_key(safe_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredArtifact(
            storage_key=safe_key,
            content_type=content_type,
            file_size_bytes=target.stat().st_size,
            checksum=self._sha256(target),
        )

    def exists(self, storage_key: str) -> bool:
        return self._resolve_key(sanitize_storage_key(storage_key)).is_file()

    def _resolve_key(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageKeyError(f"storage key escapes local root: {storage_key}")
        return path

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
