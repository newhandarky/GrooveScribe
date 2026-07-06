from __future__ import annotations

from pydantic import BaseModel, Field


class LocalDataSummaryResponse(BaseModel):
    schema_version: str = "1.0"
    status: str
    dry_run: bool = True
    execute_supported: bool = False
    storage_root_name: str
    job_dir_count: int
    database_status: str
    database_job_count: int | None = None
    orphan_job_dir_count: int
    warnings: list[str] = Field(default_factory=list)
