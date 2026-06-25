from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.storage.types import ArtifactRef, DownloadUrl


class StorageAdapter(ABC):
    @abstractmethod
    def put_file(
        self,
        source_path: Path,
        storage_key: str,
        content_type: str,
    ) -> ArtifactRef:
        raise NotImplementedError

    @abstractmethod
    def put_bytes(
        self,
        content: bytes,
        storage_key: str,
        content_type: str,
    ) -> ArtifactRef:
        raise NotImplementedError

    @abstractmethod
    def open_reader(self, storage_key: str) -> BinaryIO:
        raise NotImplementedError

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def stat(self, storage_key: str) -> ArtifactRef:
        raise NotImplementedError

    @abstractmethod
    def create_download_url(
        self,
        storage_key: str,
        expires_in_seconds: int | None = None,
    ) -> DownloadUrl:
        raise NotImplementedError
