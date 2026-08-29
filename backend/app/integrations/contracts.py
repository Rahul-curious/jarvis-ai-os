"""Framework-neutral contracts for future external service integrations.

This module contains descriptions and boundaries only. It does not persist
credentials, enforce application authorization, or call an external service.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.errors import (
    IntegrationCapabilityError,
    IntegrationConfigurationError,
    IntegrationCredentialError,
    IntegrationPermissionError,
    IntegrationProviderUnavailableError,
    IntegrationValidationError,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:/-]{0,159}$")
_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SECRET_METADATA_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "client_secret",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def _required_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase stable identifier")
    return normalized


def _scope_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _SCOPE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a stable scope identifier")
    return normalized


def _reference_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _REFERENCE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a safe credential reference")
    return normalized


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _json_mapping(value: dict[str, Any], field_name: str) -> dict[str, Any]:
    try:
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-serializable values") from exc
    return dict(sorted(value.items()))


def _canonical_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_scope_identifier(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


class IntegrationStatus(StrEnum):
    """Provider availability advertised to callers and control-plane services."""

    available = "available"
    degraded = "degraded"
    disabled = "disabled"
    unavailable = "unavailable"


class IntegrationResponseStatus(StrEnum):
    """Provider-neutral result states for a future operation boundary."""

    succeeded = "succeeded"
    accepted = "accepted"
    failed = "failed"
    rejected = "rejected"


class CredentialType(StrEnum):
    """Descriptive credential classes; storage and lifecycle are out of scope."""

    oauth2 = "oauth2"
    api_key = "api_key"
    service_account = "service_account"
    device = "device"


class PermissionRisk(StrEnum):
    """Sensitivity metadata used to describe a permission scope."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProviderIdentity(BaseModel):
    """Stable identity and display metadata for one provider."""

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=2, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=32)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "provider_id")

    @field_validator("display_name", "version")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _required_text(value, "provider metadata value")


class IntegrationCapability(BaseModel):
    """A descriptive operation a provider may support, such as read or search."""

    model_config = ConfigDict(frozen=True)

    capability_id: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    read_only: bool = True

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        return _required_identifier(value, "capability_id")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _required_text(value, "capability description")


class PermissionScope(BaseModel):
    """An explicit provider permission declaration, not an authorization grant."""

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=2, max_length=120)
    scope_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    risk: PermissionRisk = PermissionRisk.low

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "permission provider_id")

    @field_validator("scope_id")
    @classmethod
    def validate_scope_id(cls, value: str) -> str:
        return _scope_identifier(value, "scope_id")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _required_text(value, "permission description")


class IntegrationMetadata(BaseModel):
    """Complete provider discovery metadata with deterministic collection order."""

    model_config = ConfigDict(frozen=True)

    identity: ProviderIdentity
    description: str = Field(min_length=1, max_length=2000)
    status: IntegrationStatus = IntegrationStatus.available
    capabilities: tuple[IntegrationCapability, ...] = Field(default_factory=tuple)
    required_permissions: tuple[PermissionScope, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _required_text(value, "integration description")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "integration metadata")

    @model_validator(mode="after")
    def validate_collections(self) -> IntegrationMetadata:
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise IntegrationConfigurationError("provider capabilities must not contain duplicates")
        permission_ids = [(item.provider_id, item.scope_id) for item in self.required_permissions]
        if len(permission_ids) != len(set(permission_ids)):
            raise IntegrationConfigurationError("provider permissions must not contain duplicates")
        if any(
            permission.provider_id != self.identity.provider_id
            for permission in self.required_permissions
        ):
            raise IntegrationConfigurationError(
                "provider permissions must reference the provider identity"
            )
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(self.capabilities, key=lambda item: item.capability_id)),
        )
        object.__setattr__(
            self,
            "required_permissions",
            tuple(sorted(self.required_permissions, key=lambda item: item.scope_id)),
        )
        return self


class CredentialReference(BaseModel):
    """Opaque reference to externally managed credentials.

    Only a reference identifier and non-secret metadata are accepted. Plaintext
    access tokens, refresh tokens, API keys, and client secrets are rejected.
    Credential storage and OAuth lifecycle belong to a later milestone.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=2, max_length=120)
    reference_id: str = Field(min_length=1, max_length=256)
    credential_type: CredentialType
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "credential provider_id")

    @field_validator("reference_id")
    @classmethod
    def validate_reference_id(cls, value: str) -> str:
        return _reference_identifier(value, "reference_id")

    @field_validator("metadata")
    @classmethod
    def validate_credential_metadata(
        cls,
        value: dict[str, str | int | bool | None],
    ) -> dict[str, str | int | bool | None]:
        for key in value:
            normalized_key = key.strip().lower()
            if normalized_key in _SECRET_METADATA_KEYS or normalized_key.endswith(
                ("_token", "_secret", "_api_key")
            ):
                raise IntegrationCredentialError(
                    f"credential metadata must not contain secret field: {key}"
                )
        return dict(sorted(value.items()))


class IntegrationRequest(BaseModel):
    """Typed, provider-neutral input for a future integration operation."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    capability: str = Field(min_length=2, max_length=120)
    requested_scopes: tuple[str, ...] = Field(default_factory=tuple)
    credential: CredentialReference | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "correlation_id", "user_id", "workspace_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "request provider_id")

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        return _required_identifier(value, "capability")

    @field_validator("requested_scopes")
    @classmethod
    def normalize_requested_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "requested_scopes")

    @field_validator("parameters", "metadata")
    @classmethod
    def validate_json_mappings(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _json_mapping(value, str(info.field_name))

    @field_validator("user_id")
    @classmethod
    def require_user_id(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("user_id must be supplied")
        return _required_text(value, "user_id")


class IntegrationErrorInfo(BaseModel):
    """Safe structured failure information returned by a provider boundary."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def validate_error_code(cls, value: str) -> str:
        return _required_identifier(value, "error code")

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return _required_text(value, "error message")

    @field_validator("metadata")
    @classmethod
    def validate_error_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "error metadata")


class IntegrationResponse(BaseModel):
    """Typed result envelope for future asynchronous provider operations."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    capability: str = Field(min_length=2, max_length=120)
    status: IntegrationResponseStatus
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: IntegrationErrorInfo | None = None

    @field_validator("request_id", "correlation_id")
    @classmethod
    def normalize_response_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "response provider_id")

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        return _required_identifier(value, "response capability")

    @field_validator("result", "metadata")
    @classmethod
    def validate_response_json(
        cls,
        value: dict[str, Any] | None,
        info: Any,
    ) -> dict[str, Any] | None:
        return None if value is None else _json_mapping(value, str(info.field_name))

    @model_validator(mode="after")
    def validate_result_state(self) -> IntegrationResponse:
        successful = {
            IntegrationResponseStatus.succeeded,
            IntegrationResponseStatus.accepted,
        }
        failed = {
            IntegrationResponseStatus.failed,
            IntegrationResponseStatus.rejected,
        }
        if self.status in successful and self.error is not None:
            raise IntegrationValidationError("successful responses must not contain an error")
        if self.status in failed and self.error is None:
            raise IntegrationValidationError("failed responses must contain error information")
        return self


@runtime_checkable
class IntegrationProvider(Protocol):
    """Async provider boundary implemented by future external integrations."""

    @property
    def metadata(self) -> IntegrationMetadata:
        """Return stable provider identity and capability metadata."""

    def supports_capability(self, capability: str) -> bool:
        """Report whether this provider advertises a capability identifier."""

    async def execute(self, request: IntegrationRequest) -> IntegrationResponse:
        """Execute one validated operation in a provider implementation."""


def validate_provider_request(
    provider: IntegrationProvider,
    request: IntegrationRequest,
) -> None:
    """Validate request/provider compatibility without executing the provider."""

    metadata = provider.metadata
    provider_id = metadata.identity.provider_id
    if request.provider_id != provider_id:
        raise IntegrationValidationError(
            f"request provider {request.provider_id!r} does not match {provider_id!r}"
        )
    if metadata.status in {
        IntegrationStatus.disabled,
        IntegrationStatus.unavailable,
    }:
        raise IntegrationProviderUnavailableError(
            f"integration provider is {metadata.status.value}: {provider_id}"
        )
    if not provider.supports_capability(request.capability):
        raise IntegrationCapabilityError(
            f"provider {provider_id!r} does not support {request.capability!r}"
        )
    if request.credential is not None and request.credential.provider_id != provider_id:
        raise IntegrationCredentialError(
            "credential reference provider does not match the request provider"
        )
    required_scopes = {scope.scope_id for scope in metadata.required_permissions}
    requested_scopes = set(request.requested_scopes)
    missing_scopes = sorted(required_scopes - requested_scopes)
    if missing_scopes:
        raise IntegrationPermissionError(
            f"request must explicitly declare required scopes: {', '.join(missing_scopes)}"
        )
