from __future__ import annotations

from dataclasses import dataclass

from app.storage.base import StorageAdapter
from app.storage.errors import ArtifactInvalidError, ArtifactNotFoundError, PathTraversalRejectedError, StorageReadFailedError
from app.storage.keys import sanitize_storage_key
from app.storage.types import ArtifactType, CONTENT_TYPE_BY_ARTIFACT_TYPE


@dataclass(frozen=True)
class ArtifactIntegrity:
    available: bool
    reason_code: str | None = None


class ArtifactIntegrityService:
    """Validate a public artifact reference without exposing storage diagnostics."""

    def __init__(self, *, storage: StorageAdapter) -> None:
        self.storage = storage

    def check(
        self,
        *,
        storage_key: str | None,
        artifact_type: ArtifactType,
        content_type: str | None = None,
        checksum: str | None = None,
    ) -> ArtifactIntegrity:
        if not storage_key:
            return ArtifactIntegrity(False, "artifact_unavailable")
        if content_type is not None and not _content_type_matches(artifact_type, content_type):
            return ArtifactIntegrity(False, "artifact_unavailable")
        try:
            safe_key = sanitize_storage_key(storage_key)
            if safe_key != storage_key:
                return ArtifactIntegrity(False, "artifact_unavailable")
            ref = self.storage.stat(safe_key)
        except (ArtifactInvalidError, ArtifactNotFoundError, PathTraversalRejectedError, StorageReadFailedError, OSError, ValueError):
            return ArtifactIntegrity(False, "artifact_unavailable")
        if checksum and ref.checksum != checksum:
            return ArtifactIntegrity(False, "artifact_unavailable")
        return ArtifactIntegrity(True)


def _content_type_matches(artifact_type: ArtifactType, content_type: str) -> bool:
    if artifact_type == ArtifactType.ORIGINAL_AUDIO:
        return content_type == "application/octet-stream" or content_type.startswith("audio/")
    return content_type == CONTENT_TYPE_BY_ARTIFACT_TYPE[artifact_type]
