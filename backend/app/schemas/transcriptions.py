from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UploadAcceptedResponse(BaseModel):
    job_id: str
    status: str = Field(examples=["queued"])
    status_url: str
    result_url: str
    created_at: datetime
