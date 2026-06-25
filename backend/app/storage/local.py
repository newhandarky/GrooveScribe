from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO

from app.storage.base import StorageAdapter
from app.storage.errors import (
    ArtifactInvalidError,
    ArtifactNotFoundError,
    PathTraversalRejectedError,
    StorageReadFailedError,
    StorageWriteFailedError,
)
from app.storage.keys import sanitize_storage_key
from app.storage.types import ArtifactRef, DownloadUrl


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, source_path: Path, storage_key: str, content_type: str) -> ArtifactRef:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise StorageWriteFailedError(f"source file does not exist: {source_path}")

        target = self._resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            raise StorageWriteFailedError(str(exc)) from exc
        return self._build_ref(storage_key, content_type)

    def put_bytes(self, content: bytes, storage_key: str, content_type: str) -> ArtifactRef:
        target = self._resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(content)
        except OSError as exc:
            raise StorageWriteFailedError(str(exc)) from exc
        return self._build_ref(storage_key, content_type)

    def open_reader(self, storage_key: str) -> BinaryIO:
        path = self._resolve_existing_key(storage_key)
        try:
            return path.open("rb")
        except OSError as exc:
            raise StorageReadFailedError(str(exc)) from exc

    def exists(self, storage_key: str) -> bool:
        path = self._resolve_key(storage_key)
        return path.exists() and path.is_file()

    def stat(self, storage_key: str) -> ArtifactRef:
        path = self._resolve_existing_key(storage_key)
        return ArtifactRef(
            storage_key=sanitize_storage_key(storage_key),
            content_type="application/octet-stream",
            file_size_bytes=path.stat().st_size,
            checksum=self._sha256(path),
        )

    def create_download_url(
        self,
        storage_key: str,
        expires_in_seconds: int | None = None,
    ) -> DownloadUrl:
        safe_key = sanitize_storage_key(storage_key)
        return DownloadUrl(url=f"/api/v1/storage/local/{safe_key}", expires_in_seconds=expires_in_seconds)

    def _resolve_existing_key(self, storage_key: str) -> Path:
        path = self._resolve_key(storage_key)
        if not path.exists() or not path.is_file():
            raise ArtifactNotFoundError(f"artifact not found: {storage_key}")
        if path.stat().st_size == 0:
            raise ArtifactInvalidError(f"artifact is empty: {storage_key}")
        return path

    def _resolve_key(self, storage_key: str) -> Path:
        safe_key = sanitize_storage_key(storage_key)
        path = (self.root / safe_key).resolve()
        if path != self.root and self.root not in path.parents:
            raise PathTraversalRejectedError(f"storage key escapes local root: {storage_key}")
        return path

    def _build_ref(self, storage_key: str, content_type: str) -> ArtifactRef:
        path = self._resolve_existing_key(storage_key)
        return ArtifactRef(
            storage_key=sanitize_storage_key(storage_key),
            content_type=content_type,
            file_size_bytes=path.stat().st_size,
            checksum=self._sha256(path),
        )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
