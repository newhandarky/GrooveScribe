from __future__ import annotations

from pydantic import BaseModel, Field

from app.storage.types import ArtifactType


class ArtifactRefSchema(BaseModel):
    storage_key: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)
    file_size_bytes: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    artifact_type: ArtifactType | None = None


class DownloadUrlSchema(BaseModel):
    url: str = Field(..., min_length=1)
    expires_in_seconds: int | None = Field(default=None, ge=0)
