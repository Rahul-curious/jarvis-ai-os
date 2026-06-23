from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class MemoryType(StrEnum):
    short_term = "short_term"
    long_term = "long_term"
    user_preference = "user_preference"
    project = "project"
    correction = "correction"


class MemoryReferenceCreate(BaseModel):
    reference_type: str = Field(min_length=1, max_length=64)
    reference_id: str | None = Field(default=None, max_length=128)
    label: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reference_type", "reference_id", "label", "url")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None


class MemoryReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    reference_type: str
    reference_id: str | None
    label: str | None
    url: str | None
    metadata: dict[str, Any] = Field(
        validation_alias="reference_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime


class MemoryCreateRequest(BaseModel):
    memory_type: MemoryType
    category: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
    importance_score: float = Field(default=0.5, ge=0, le=1)
    source: str = Field(default="manual", min_length=1, max_length=120)
    expires_at: datetime | None = None
    references: list[MemoryReferenceCreate] = Field(default_factory=list, max_length=25)

    @field_validator("category", "content", "source")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_required_strings(self) -> MemoryCreateRequest:
        if not self.category:
            raise ValueError("category must not be blank")
        if not self.content:
            raise ValueError("content must not be blank")
        if not self.source:
            raise ValueError("source must not be blank")
        return self


class MemoryUpdateRequest(BaseModel):
    memory_type: MemoryType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    importance_score: float | None = Field(default=None, ge=0, le=1)
    source: str | None = Field(default=None, min_length=1, max_length=120)
    expires_at: datetime | None = None
    references: list[MemoryReferenceCreate] | None = Field(default=None, max_length=25)

    @field_validator("category", "content", "source")
    @classmethod
    def strip_optional_required_strings(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip()

    @model_validator(mode="after")
    def validate_update_payload(self) -> MemoryUpdateRequest:
        provided_fields = self.model_fields_set
        if not provided_fields:
            raise ValueError("at least one memory field must be provided")
        for field_name in ("category", "content", "source"):
            value = getattr(self, field_name)
            if field_name in provided_fields and value == "":
                raise ValueError(f"{field_name} must not be blank")
        return self


class MemoryRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    memory_type: MemoryType
    category: str
    content: str
    importance_score: float
    reinforcement_count: int
    memory_score: float
    source: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    references: list[MemoryReferenceRead] = Field(default_factory=list)


class MemoryListResponse(BaseModel):
    items: list[MemoryRead]
    total: int
    limit: int
    offset: int


class MemorySearchRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    memory_type: MemoryType | None = None
    min_importance_score: float | None = Field(default=None, ge=0, le=1)
    include_expired: bool = False
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("keyword", "category")
    @classmethod
    def strip_search_strings(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None


class MemoryReinforceRequest(BaseModel):
    memory_id: uuid.UUID
    amount: int = Field(default=1, ge=1, le=10)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None


class MemoryDeleteResponse(BaseModel):
    detail: str
