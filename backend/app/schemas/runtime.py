from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RuntimePreflightStatus = Literal["ready", "degraded", "not_ready", "error"]


class RuntimePreflightError(BaseModel):
    code: str
    message: str


class RuntimePreflightResponse(BaseModel):
    status: RuntimePreflightStatus
    generic_baseline_ready: bool = False
    demo_mock_ready: bool = False
    # Deprecated aliases retained for one v1 compatibility window. `true_ai`
    # remains false because it is no longer a public runtime mode.
    mock_ai_ready: bool = False
    true_ai_ready: bool = False
    missing_requirements: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    offline_evaluation: dict[str, Any] = Field(default_factory=dict)
    smoke_commands: dict[str, str] = Field(default_factory=dict)
    checked_at: datetime
    error: RuntimePreflightError | None = None
