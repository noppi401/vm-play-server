"""Pydantic v2 models for execution requests, responses, and session state."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ExecutionStatus(str, Enum):
    """Lifecycle states for a single execution session."""

    PENDING = "pending"
    GENERATING = "generating"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class StrictBaseModel(BaseModel):
    """Shared configuration for API schemas."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RunRequest(StrictBaseModel):
    """Request body for starting an AI-generated execution."""

    instruction: str = Field(
        ...,
        min_length=1,
        description="Natural-language instruction used to generate executable code.",
    )

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        """Reject instructions that contain only whitespace."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be empty")
        return normalized


class RunResponse(StrictBaseModel):
    """202 Accepted response for a started run."""

    execution_id: str = Field(..., min_length=1)
    result_url: str | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING


class StopResponse(StrictBaseModel):
    """Response returned after a stop request."""

    execution_id: str | None = None
    status: ExecutionStatus
    message: str = Field(..., min_length=1)


class ErrorResponse(StrictBaseModel):
    """Structured error payload returned by the HTTP API."""

    error: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    details: dict[str, Any] | None = None


class ExecutionSession(StrictBaseModel):
    """Internal state model representing one execution lifecycle."""

    execution_id: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)
    status: ExecutionStatus = ExecutionStatus.PENDING
    result_url: str | None = None
    container_id: str | None = None
    code_path: str | None = None
    log_path: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None
    error_message: str | None = None

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        """Reject blank session instructions."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be empty")
        return normalized

    def mark_status(self, status: ExecutionStatus, *, error_message: str | None = None) -> None:
        """Update session status and timestamps consistently."""
        self.status = status
        self.updated_at = _utc_now()
        self.error_message = error_message
        if status in {
            ExecutionStatus.STOPPED,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
        }:
            self.completed_at = self.updated_at
