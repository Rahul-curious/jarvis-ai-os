from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentDefinitionStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    archived = "archived"


class AgentRunStatus(StrEnum):
    requested = "requested"
    validating = "validating"
    queued = "queued"
    running = "running"
    waiting_for_approval = "waiting_for_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    retriable = "retriable"


class AgentStepStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    skipped = "skipped"


class ContextLimits(BaseModel):
    """Boundaries applied while assembling an execution context."""

    model_config = ConfigDict(frozen=True)

    max_sections: int = Field(default=20, ge=1)
    max_section_bytes: int = Field(default=64_000, ge=1)
    max_total_bytes: int = Field(default=256_000, ge=1)
    max_metadata_keys: int = Field(default=100, ge=1)
    max_metadata_bytes: int = Field(default=64_000, ge=1)
    max_conversation_messages: int = Field(default=100, ge=1)
    max_task_length: int = Field(default=20_000, ge=1)

    @model_validator(mode="after")
    def validate_total_limit(self) -> ContextLimits:
        if self.max_total_bytes < self.max_section_bytes:
            raise ValueError("max_total_bytes must be greater than or equal to max_section_bytes")
        return self


class ContextMetadata(BaseModel):
    """Metadata describing the assembled context payload."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = Field(default=None, max_length=128)
    assembled_at: datetime
    provider_names: tuple[str, ...] = Field(default_factory=tuple)
    section_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)


class ContextSection(BaseModel):
    """A named, prioritized contribution from one context provider."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=120)
    priority: int = Field(ge=0, le=10_000)
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def strip_provider(cls, value: str) -> str:
        return _strip_required(value)


class ConversationMessage(BaseModel):
    """A bounded conversation item supplied to Context Assembly."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return _strip_required(value)


class UserInformation(BaseModel):
    """Safe user attributes that may be exposed to an agent runtime."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    email: str = Field(min_length=1, max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    is_active: bool = True

    @field_validator("email", "full_name")
    @classmethod
    def strip_user_values(cls, value: str) -> str:
        return _strip_required(value)


class AgentConfiguration(BaseModel):
    """Serializable agent configuration supplied to Context Assembly."""

    model_config = ConfigDict(frozen=True)

    agent_id: uuid.UUID | None = None
    agent_key: str = Field(min_length=1, max_length=120)
    agent_type: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=32)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_key", "agent_type", "version")
    @classmethod
    def strip_configuration_values(cls, value: str) -> str:
        return _strip_required(value)


class ContextAssemblyRequest(BaseModel):
    """Framework-neutral input provided to context providers."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    user_id: uuid.UUID
    task: str = Field(min_length=1, max_length=20_000)
    request_id: str | None = Field(default=None, max_length=128)
    memory_query: str | None = Field(default=None, max_length=200)
    knowledge_query: str | None = Field(default=None, max_length=2000)
    conversation_history: tuple[ConversationMessage, ...] = Field(default_factory=tuple)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    user_information: UserInformation
    agent_configuration: AgentConfiguration

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("request_id")
    @classmethod
    def strip_request_id(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("memory_query")
    @classmethod
    def strip_memory_query(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("knowledge_query")
    @classmethod
    def strip_knowledge_query(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def validate_user_identity(self) -> ContextAssemblyRequest:
        if self.user_information.user_id != self.user_id:
            raise ValueError("user_information.user_id must match user_id")
        return self


class ExecutionContext(BaseModel):
    """Validated context passed to a future runtime implementation."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    user_id: uuid.UUID
    task: str
    sections: tuple[ContextSection, ...] = Field(default_factory=tuple)
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: ContextMetadata

    @property
    def merged_data(self) -> dict[str, Any]:
        """Compatibility-friendly name for the merged provider payload."""

        return self.data


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped


class AgentDefinitionCreateRequest(BaseModel):
    agent_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    agent_type: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    version: str = Field(default="1.0", min_length=1, max_length=32)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_key", "name", "agent_type", "version")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class AgentDefinitionUpdateRequest(BaseModel):
    agent_key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    agent_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    version: str | None = Field(default=None, min_length=1, max_length=32)
    status: AgentDefinitionStatus | None = None
    configuration: dict[str, Any] | None = None

    @field_validator("agent_key", "name", "agent_type", "version")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def strip_optional_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def require_update(self) -> AgentDefinitionUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one definition field must be provided")
        return self


class AgentRunCreateRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=128)
    agent_type: str = Field(min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=20000)
    agent_definition_id: uuid.UUID | None = None
    conversation_history: tuple[ConversationMessage, ...] = Field(default_factory=tuple)
    memory_query: str | None = Field(default=None, max_length=200)
    knowledge_query: str | None = Field(default=None, max_length=2000)
    requested_tool_ids: tuple[str, ...] = Field(default_factory=tuple)
    input_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_type", "task")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("request_id", "memory_query", "knowledge_query")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("requested_tool_ids")
    @classmethod
    def normalize_requested_tool_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_strip_required(tool_id) for tool_id in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("requested_tool_ids must not contain duplicates")
        return normalized


class AgentRunStatusUpdateRequest(BaseModel):
    status: AgentRunStatus
    output_text: str | None = Field(default=None, max_length=100000)
    output_metadata: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=5000)
    increment_retry_count: bool = False

    @field_validator("output_text", "error_code", "error_message")
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class AgentStepCreateRequest(BaseModel):
    step_index: int = Field(ge=0)
    step_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    status: AgentStepStatus = AgentStepStatus.pending
    input_metadata: dict[str, Any] = Field(default_factory=dict)
    output_metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=5000)

    @field_validator("step_type", "name")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("error_code", "error_message")
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class AgentEventCreateRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    sequence: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=32)
    message: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    step_id: uuid.UUID | None = None

    @field_validator("event_type")
    @classmethod
    def strip_event_type(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("status", "message")
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class AgentArtifactCreateRequest(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=120)
    storage_uri: str | None = Field(default=None, max_length=4096)
    checksum_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    size_bytes: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_type", "name")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("content_type", "storage_uri", "checksum_sha256")
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None


class AgentDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_key: str
    name: str
    agent_type: str
    description: str | None
    version: str
    status: AgentDefinitionStatus
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    step_index: int
    step_type: str
    name: str
    status: AgentStepStatus
    input_metadata: dict[str, Any]
    output_metadata: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    step_id: uuid.UUID | None
    sequence: int
    event_type: str
    status: str | None
    message: str | None
    metadata: dict[str, Any] = Field(
        validation_alias="event_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime


class AgentArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    artifact_type: str
    name: str
    content_type: str | None
    storage_uri: str | None
    checksum_sha256: str | None
    size_bytes: int
    metadata: dict[str, Any] = Field(
        validation_alias="artifact_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_definition_id: uuid.UUID | None
    agent_type: str
    task: str
    status: AgentRunStatus
    input_metadata: dict[str, Any]
    output_text: str | None
    output_metadata: dict[str, Any]
    error_code: str | None
    error_message: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    steps: list[AgentStepRead] = Field(default_factory=list)
    events: list[AgentEventRead] = Field(default_factory=list)
    artifacts: list[AgentArtifactRead] = Field(default_factory=list)


class AgentRunListResponse(BaseModel):
    items: list[AgentRunRead]
    total: int
    limit: int
    offset: int


class AgentDefinitionListResponse(BaseModel):
    items: list[AgentDefinitionRead]
    total: int
    limit: int
    offset: int


class AgentEventListResponse(BaseModel):
    items: list[AgentEventRead]
    total: int
