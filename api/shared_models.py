"""Shared Pydantic models used across multiple endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseResponse(BaseModel):
    id: UUID
    content: str
    task_type: Optional[str] = None
    steps: Optional[list[str]] = None
    result: Optional[str] = None
    success: Optional[bool] = None
    skill_id: Optional[UUID] = None
    created_at: datetime


class TensionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(..., pattern="^(resolve|dismiss)$")
    note: Optional[str] = Field(None, max_length=1000)

    @field_validator("note")
    @classmethod
    def _no_nulls(cls, v):
        if v is not None and "\x00" in v:
            raise ValueError("note contains null bytes")
        return v
