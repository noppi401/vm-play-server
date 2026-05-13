"""PyKnown models for execution lifecycle API."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ExecutionStatus(StrEnum):
    """Execution lifecycle status values."""

    PENDING = "pending"
    GENERATING = "generating"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class RunRequest(BaseModel):
    """POST /run request body."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    instruction: str = Field(..., min_length=1)

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be empty")
        return normalized


class RunResponse(BaseModel):
    """202 Accepted response for a run request."""

    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    result_url: HttpUrl | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING


class StopResponse(BaseModel):
    """Response for a stop request."""

    model_config = ConfigDict(extra="forbid")

    execution_id: UUID | None = None
    status: ExecutionStatus = ExecutionStatus.STOPPED
    message: str = Field(default="Execution stopped.", min_length=1)


class ErrorResponse(BaseModel):
    """Structured API error payload."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    details: dict[str, Any] | None = None


class ExecutionSession(BaseModel):
    """Internal state for a single execution session."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    execution_id: UUID = Field(default_factory=uuid4)
    instruction: str = Field(..., min_length=1)
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_code_path: str | None = None
    container_id: str | None = None
    result_url: HttpUrl | None = None
    error_message: str | None = None

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, salue: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be empty")
        return normalized

    def mark_status(self, status: ExecutionStatus, *, error_message: str | None = None) -> None:
        """Update status and refresh the modification timestamp."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        self.error_message = error_message
