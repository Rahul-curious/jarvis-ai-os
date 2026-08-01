from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.agents.errors import (
    AgentToolLimitError,
    AgentToolRegistrationError,
    AgentToolValidationError,
)

_TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_FIELD_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,119}$")


class ToolDataType(StrEnum):
    """Supported primitive shapes for a tool contract field."""

    string = "string"
    integer = "integer"
    number = "number"
    boolean = "boolean"
    object = "object"
    array = "array"
    null = "null"


class ToolState(StrEnum):
    """Descriptive registry state used during discovery."""

    enabled = "enabled"
    disabled = "disabled"


class ToolRiskLevel(StrEnum):
    """Descriptive risk metadata; this milestone does not enforce policy."""

    low = "low"
    medium = "medium"
    high = "high"


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def _canonical_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_strip_required(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


class ToolParameter(BaseModel):
    """One named field in a tool input or output contract."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)
    data_type: ToolDataType
    description: str | None = Field(default=None, max_length=2000)
    required: bool = False
    nullable: bool = False
    item_type: ToolDataType | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = _strip_required(value, "parameter name")
        if _FIELD_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("parameter name must be a stable identifier")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def validate_item_type(self) -> ToolParameter:
        if self.data_type == ToolDataType.array and self.item_type is None:
            raise ValueError("array parameters must define item_type")
        if self.data_type != ToolDataType.array and self.item_type is not None:
            raise ValueError("item_type is only valid for array parameters")
        return self


class ToolContract(BaseModel):
    """Typed, serializable contract for a tool boundary."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    fields: tuple[ToolParameter, ...] = Field(default_factory=tuple)
    allow_additional_fields: bool = False

    @model_validator(mode="after")
    def validate_fields(self) -> ToolContract:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("contract fields must not contain duplicates")
        return self


class ToolInputContract(ToolContract):
    """Input payload contract exposed for discovery and future planning."""


class ToolOutputContract(ToolContract):
    """Output payload contract exposed for discovery and future planning."""


class ToolPolicyMetadata(BaseModel):
    """Descriptive policy metadata; no authorization or approval is executed."""

    model_config = ConfigDict(frozen=True)

    risk_level: ToolRiskLevel = ToolRiskLevel.low
    requires_approval: bool = False
    permission_scopes: tuple[str, ...] = Field(default_factory=tuple)
    policy_tags: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("permission_scopes", "policy_tags")
    @classmethod
    def normalize_metadata_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "policy metadata values")


class ToolMetadata(BaseModel):
    """Human-readable and descriptive metadata for a registered tool."""

    model_config = ConfigDict(frozen=True)

    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    version: str = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=64)
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    state: ToolState = ToolState.enabled
    policy: ToolPolicyMetadata = Field(default_factory=ToolPolicyMetadata)

    @field_validator("display_name", "description", "version", "category")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _strip_required(value, "tool metadata value")

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "capabilities")


class ToolDefinition(BaseModel):
    """Complete, immutable tool contract registered for future discovery."""

    model_config = ConfigDict(frozen=True)

    tool_id: str = Field(min_length=2, max_length=120)
    metadata: ToolMetadata
    input_contract: ToolInputContract
    output_contract: ToolOutputContract

    @field_validator("tool_id")
    @classmethod
    def validate_tool_id(cls, value: str) -> str:
        value = _strip_required(value, "tool_id")
        if _TOOL_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("tool_id must be a lowercase stable identifier")
        return value


class ToolRegistryLimits(BaseModel):
    """Explicit bounds that protect registry discovery metadata."""

    model_config = ConfigDict(frozen=True)

    max_tools: int = Field(default=256, ge=1)
    max_capabilities_per_tool: int = Field(default=32, ge=1)
    max_policy_values_per_tool: int = Field(default=32, ge=1)
    max_contract_fields: int = Field(default=128, ge=1)


@runtime_checkable
class Tool(Protocol):
    """Read-only tool descriptor protocol with no execution operation."""

    definition: ClassVar[ToolDefinition]


ToolRegistration = ToolDefinition | Tool


class ToolRegistry:
    """Explicit, per-instance registry for framework-neutral tool contracts."""

    def __init__(
        self,
        tools: Iterable[ToolRegistration] = (),
        *,
        limits: ToolRegistryLimits | None = None,
    ) -> None:
        self.limits = limits or ToolRegistryLimits()
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    @property
    def count(self) -> int:
        return len(self._tools)

    def register(self, tool: ToolRegistration) -> ToolDefinition:
        definition = self._get_definition(tool)
        self._validate_limits(definition)
        if definition.tool_id in self._tools:
            raise AgentToolRegistrationError(
                f"Tool is already registered: {definition.tool_id}"
            )
        if self.count >= self.limits.max_tools:
            raise AgentToolLimitError("Tool registry has reached its maximum size")
        self._tools[definition.tool_id] = definition
        return definition

    register_tool = register

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(self._normalize_tool_id(tool_id))

    get_definition = get

    def exists(self, tool_id: str) -> bool:
        return self._normalize_tool_id(tool_id) in self._tools

    def list_tools(
        self,
        *,
        category: str | None = None,
        capability: str | None = None,
        include_disabled: bool = False,
    ) -> tuple[ToolDefinition, ...]:
        normalized_category = (
            _strip_required(category, "category") if category is not None else None
        )
        normalized_capability = (
            _strip_required(capability, "capability") if capability is not None else None
        )
        definitions = self._tools.values()
        filtered = (
            definition
            for definition in definitions
            if (include_disabled or definition.metadata.state == ToolState.enabled)
            and (
                normalized_category is None
                or definition.metadata.category == normalized_category
            )
            and (
                normalized_capability is None
                or normalized_capability in definition.metadata.capabilities
            )
        )
        return tuple(sorted(filtered, key=lambda definition: definition.tool_id))

    discover = list_tools
    discover_tools = list_tools

    def _get_definition(self, tool: ToolRegistration) -> ToolDefinition:
        if isinstance(tool, ToolDefinition):
            return tool
        try:
            definition = tool.definition
        except AttributeError as exc:
            raise AgentToolValidationError(
                "Registered tool must expose a ToolDefinition"
            ) from exc
        if not isinstance(definition, ToolDefinition):
            raise AgentToolValidationError(
                "Registered tool must expose a ToolDefinition"
            )
        return definition

    def _validate_limits(self, definition: ToolDefinition) -> None:
        metadata = definition.metadata
        if len(metadata.capabilities) > self.limits.max_capabilities_per_tool:
            raise AgentToolLimitError(
                f"Tool {definition.tool_id!r} has too many capabilities"
            )
        policy_values = len(metadata.policy.permission_scopes) + len(metadata.policy.policy_tags)
        if policy_values > self.limits.max_policy_values_per_tool:
            raise AgentToolLimitError(
                f"Tool {definition.tool_id!r} has too many policy metadata values"
            )
        contract_fields = len(definition.input_contract.fields) + len(
            definition.output_contract.fields
        )
        if contract_fields > self.limits.max_contract_fields:
            raise AgentToolLimitError(
                f"Tool {definition.tool_id!r} has too many contract fields"
            )

    @staticmethod
    def _normalize_tool_id(tool_id: str) -> str:
        normalized = _strip_required(tool_id, "tool_id")
        if _TOOL_ID_PATTERN.fullmatch(normalized) is None:
            raise AgentToolValidationError("tool_id must be a lowercase stable identifier")
        return normalized
