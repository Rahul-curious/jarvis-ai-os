"""Framework-neutral contracts for future external service integrations.

This module contains descriptions and boundaries only. It does not persist
credentials, enforce application authorization, or call an external service.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.errors import (
    CredentialLifecycleError,
    IntegrationCapabilityError,
    IntegrationConfigurationError,
    IntegrationCredentialError,
    IntegrationPermissionError,
    IntegrationProviderUnavailableError,
    IntegrationValidationError,
    OAuthStateError,
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


def _aware_timestamp(value: datetime | None, field_name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must include timezone information")
    return value


def _required_aware_timestamp(value: datetime, field_name: str) -> datetime:
    normalized = _aware_timestamp(value, field_name)
    if normalized is None:
        raise ValueError(f"{field_name} must not be null")
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


class CredentialStatus(StrEnum):
    """Explicit lifecycle states for an opaque credential reference."""

    pending = "pending"
    active = "active"
    expired = "expired"
    revoked = "revoked"
    disabled = "disabled"
    error = "error"


_CREDENTIAL_STATUS_TRANSITIONS = MappingProxyType(
    {
        CredentialStatus.pending: frozenset(
            {CredentialStatus.active, CredentialStatus.disabled, CredentialStatus.error}
        ),
        CredentialStatus.active: frozenset(
            {
                CredentialStatus.expired,
                CredentialStatus.revoked,
                CredentialStatus.disabled,
                CredentialStatus.error,
            }
        ),
        CredentialStatus.expired: frozenset(
            {CredentialStatus.revoked, CredentialStatus.disabled, CredentialStatus.error}
        ),
        CredentialStatus.revoked: frozenset(),
        CredentialStatus.disabled: frozenset({CredentialStatus.active, CredentialStatus.error}),
        CredentialStatus.error: frozenset({CredentialStatus.pending, CredentialStatus.disabled}),
    }
)


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


class CredentialOwnership(BaseModel):
    """Explicit ownership context for a credential reference."""

    model_config = ConfigDict(frozen=True)

    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("user_id", "workspace_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def require_owner_context(self) -> CredentialOwnership:
        if self.user_id is None and self.workspace_id is None:
            raise ValueError("credential ownership must include a user_id or workspace_id")
        return self


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
    status: CredentialStatus = CredentialStatus.active
    ownership: CredentialOwnership | None = None
    granted_scopes: tuple[str, ...] = Field(default_factory=tuple)
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

    @field_validator("granted_scopes")
    @classmethod
    def normalize_granted_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "granted_scopes")

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        return _aware_timestamp(value, "credential expires_at")

    @model_validator(mode="after")
    def validate_lifecycle_metadata(self) -> CredentialReference:
        if self.status == CredentialStatus.expired and self.expires_at is None:
            raise IntegrationCredentialError("expired credentials must include expiration metadata")
        return self


class CredentialResolution(BaseModel):
    """Non-secret result metadata returned by a future credential resolver."""

    model_config = ConfigDict(frozen=True)

    reference: CredentialReference
    resolved_at: datetime
    status: CredentialStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("resolved_at")
    @classmethod
    def validate_resolved_at(cls, value: datetime) -> datetime:
        return _required_aware_timestamp(value, "credential resolved_at")

    @field_validator("metadata")
    @classmethod
    def validate_resolution_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "credential resolution metadata")

    @model_validator(mode="after")
    def match_reference_status(self) -> CredentialResolution:
        if self.status != self.reference.status:
            raise IntegrationCredentialError(
                "credential resolution status must match the reference status"
            )
        return self


class CredentialRevocationStatus(StrEnum):
    """Result states for a future provider-neutral revocation operation."""

    accepted = "accepted"
    revoked = "revoked"
    failed = "failed"
    unsupported = "unsupported"


class CredentialRevocationRequest(BaseModel):
    """Explicitly scoped revocation request without secret material."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    credential: CredentialReference
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "correlation_id", "user_id", "workspace_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("metadata")
    @classmethod
    def validate_request_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "credential revocation metadata")

    @model_validator(mode="after")
    def validate_ownership(self) -> CredentialRevocationRequest:
        _validate_ownership_context(
            ownership=self.credential.ownership,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )
        return self


class CredentialRevocationResult(BaseModel):
    """Structured revocation result that contains no credential secret."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    reference_id: str = Field(min_length=1, max_length=256)
    status: CredentialRevocationStatus
    revoked_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: IntegrationErrorInfo | None = None

    @field_validator("revoked_at")
    @classmethod
    def validate_revoked_at(cls, value: datetime | None) -> datetime | None:
        return _aware_timestamp(value, "credential revoked_at")

    @field_validator("request_id", "correlation_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "revocation provider_id")

    @field_validator("reference_id")
    @classmethod
    def validate_reference_id(cls, value: str) -> str:
        return _reference_identifier(value, "revocation reference_id")

    @field_validator("metadata")
    @classmethod
    def validate_result_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "credential revocation result metadata")

    @model_validator(mode="after")
    def validate_result_state(self) -> CredentialRevocationResult:
        success_states = {
            CredentialRevocationStatus.accepted,
            CredentialRevocationStatus.revoked,
        }
        failure_states = {
            CredentialRevocationStatus.failed,
            CredentialRevocationStatus.unsupported,
        }
        if self.status in success_states and self.error is not None:
            raise IntegrationValidationError("successful revocation must not contain an error")
        if self.status in failure_states and self.error is None:
            raise IntegrationValidationError("failed revocation must contain error information")
        return self


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


class ScopeComparison(BaseModel):
    """Deterministic comparison between requested and granted permissions."""

    model_config = ConfigDict(frozen=True)

    requested: tuple[str, ...]
    granted: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]

    @property
    def is_satisfied(self) -> bool:
        return not self.missing and not self.unexpected


class OAuthAuthorizationState(BaseModel):
    """Short-lived state used to bind a future OAuth callback to its request."""

    model_config = ConfigDict(frozen=True)

    state_id: str = Field(min_length=1, max_length=256)
    provider_id: str = Field(min_length=2, max_length=120)
    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return _required_aware_timestamp(value, "OAuth state timestamp")

    @field_validator("state_id")
    @classmethod
    def validate_state_id(cls, value: str) -> str:
        return _reference_identifier(value, "state_id")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "OAuth state provider_id")

    @field_validator("request_id", "correlation_id", "user_id", "workspace_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def validate_expiration(self) -> OAuthAuthorizationState:
        if self.expires_at <= self.created_at:
            raise OAuthStateError("OAuth state expires_at must be after created_at")
        if (self.expires_at - self.created_at).total_seconds() > 3600:
            raise OAuthStateError("OAuth state lifetime must not exceed one hour")
        return self


class OAuthAuthorizationRequest(BaseModel):
    """Provider-neutral delegated authorization request metadata."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    client_reference: str = Field(min_length=1, max_length=256)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    requested_scopes: tuple[str, ...] = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    state: OAuthAuthorizationState
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "correlation_id", "user_id", "workspace_id")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "OAuth request provider_id")

    @field_validator("client_reference")
    @classmethod
    def validate_client_reference(cls, value: str) -> str:
        return _reference_identifier(value, "client_reference")

    @field_validator("redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("redirect_uri must be an absolute HTTP(S) URI")
        return normalized

    @field_validator("requested_scopes")
    @classmethod
    def normalize_requested_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "requested_scopes")

    @field_validator("metadata")
    @classmethod
    def validate_request_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "OAuth request metadata")

    @model_validator(mode="after")
    def validate_state_binding(self) -> OAuthAuthorizationRequest:
        state = self.state
        if (
            state.provider_id != self.provider_id
            or state.request_id != self.request_id
            or state.correlation_id != self.correlation_id
        ):
            raise OAuthStateError("OAuth state does not match the authorization request")
        if state.user_id != self.user_id or state.workspace_id != self.workspace_id:
            raise OAuthStateError("OAuth state ownership does not match the authorization request")
        return self


class OAuthTokenType(StrEnum):
    """Provider-neutral token type metadata."""

    bearer = "bearer"


class OAuthTokenResult(BaseModel):
    """Token lifecycle metadata without access or refresh token values."""

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=2, max_length=120)
    credential: CredentialReference
    token_type: OAuthTokenType = OAuthTokenType.bearer
    expires_at: datetime | None = None
    granted_scopes: tuple[str, ...] = Field(default_factory=tuple)
    refresh_available: bool = False
    refresh_expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expires_at", "refresh_expires_at")
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        return _aware_timestamp(value, "token expiration")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _required_identifier(value, "token result provider_id")

    @field_validator("granted_scopes")
    @classmethod
    def normalize_granted_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_strings(value, "granted_scopes")

    @field_validator("metadata")
    @classmethod
    def validate_token_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_mapping(value, "token result metadata")

    @model_validator(mode="after")
    def validate_token_reference(self) -> OAuthTokenResult:
        if self.credential.provider_id != self.provider_id:
            raise IntegrationCredentialError(
                "token result credential provider does not match provider_id"
            )
        if self.credential.status in {
            CredentialStatus.revoked,
            CredentialStatus.disabled,
            CredentialStatus.error,
        }:
            raise CredentialLifecycleError(
                f"token result cannot use credential status {self.credential.status.value}"
            )
        if self.refresh_available and self.refresh_expires_at is not None and self.expires_at:
            if self.refresh_expires_at <= self.expires_at:
                raise ValueError("refresh token expiration must be after access expiration")
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


@runtime_checkable
class CredentialResolver(Protocol):
    """Async boundary for resolving opaque references without exposing secrets."""

    async def resolve(self, reference: CredentialReference) -> CredentialResolution:
        """Resolve reference metadata through a future vault implementation."""


@runtime_checkable
class CredentialRevoker(Protocol):
    """Async boundary for future provider or vault credential revocation."""

    async def revoke(self, request: CredentialRevocationRequest) -> CredentialRevocationResult:
        """Request revocation without performing it in the contract layer."""


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
    _validate_ownership_context(
        ownership=request.credential.ownership if request.credential is not None else None,
        user_id=request.user_id,
        workspace_id=request.workspace_id,
    )


def compare_scopes(
    requested: tuple[str, ...] | list[str],
    granted: tuple[str, ...] | list[str],
) -> ScopeComparison:
    """Compare scopes without granting or expanding consent implicitly."""

    requested_scopes = _canonical_strings(tuple(requested), "requested scopes")
    granted_scopes = _canonical_strings(tuple(granted), "granted scopes")
    requested_set = set(requested_scopes)
    granted_set = set(granted_scopes)
    return ScopeComparison(
        requested=requested_scopes,
        granted=granted_scopes,
        missing=tuple(sorted(requested_set - granted_set)),
        unexpected=tuple(sorted(granted_set - requested_set)),
    )


def validate_credential_transition(
    current: CredentialStatus,
    target: CredentialStatus,
) -> None:
    """Validate an explicit lifecycle transition without mutating the reference."""

    current_status = CredentialStatus(current)
    target_status = CredentialStatus(target)
    if current_status == target_status:
        return
    if target_status not in _CREDENTIAL_STATUS_TRANSITIONS[current_status]:
        raise CredentialLifecycleError(
            f"credential transition {current_status.value}->{target_status.value} is not allowed"
        )


def ensure_credential_usable(
    reference: CredentialReference,
    *,
    now: datetime | None = None,
) -> None:
    """Reject every non-active or expired reference without changing its state."""

    if reference.status != CredentialStatus.active:
        raise CredentialLifecycleError(
            f"credential reference is {reference.status.value} and cannot be used"
        )
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise CredentialLifecycleError(
            "credential validation time must include timezone information"
        )
    if reference.expires_at is not None and reference.expires_at <= current_time:
        raise CredentialLifecycleError("credential reference is expired")


def validate_oauth_state(
    state: OAuthAuthorizationState,
    *,
    now: datetime | None = None,
) -> None:
    """Validate that short-lived OAuth state is still usable."""

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise OAuthStateError("OAuth validation time must include timezone information")
    if state.created_at > current_time:
        raise OAuthStateError("OAuth authorization state was created in the future")
    if state.expires_at <= current_time:
        raise OAuthStateError("OAuth authorization state has expired")


def _validate_ownership_context(
    *,
    ownership: CredentialOwnership | None,
    user_id: str,
    workspace_id: str | None,
) -> None:
    if ownership is None:
        return
    if ownership.user_id is not None and ownership.user_id != user_id:
        raise IntegrationCredentialError("credential ownership does not match request user")
    if ownership.workspace_id is not None and ownership.workspace_id != workspace_id:
        raise IntegrationCredentialError("credential ownership does not match request workspace")
