from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="User-facing error message.")
    retriable: bool = Field(description="Whether the user can retry the same action later.")
    details: dict[str, Any] = Field(default_factory=dict, description="Safe structured details for clients.")


class ErrorResponse(BaseModel):
    error: ErrorBody
