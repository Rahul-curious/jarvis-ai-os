"""Schemas and models for workspace integration bindings."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.workspaces.errors import (
    WorkspaceBindingStateError,
    WorkspaceBindingValidationError,
)
from app.integrations.contracts import (
    CredentialReference,
    CredentialStatus,
    IntegrationRequest,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,119}$")
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:/-]{0,159}$")
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "client_secret",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise WorkspaceBindingValidationError(
            f"{field_name} must be a lowercase alphanumeric identifier"
        )
    return normalized


def _validate_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise WorkspaceBindingValidationError(f"{field_name} must not be blank")
    return normalized


def _canonical_scopes(
    values: tuple[str, ...],
    field_name: str = "granted_scopes",
) -> tuple[str, ...]:
    normalized_list: list[str] = []
    for item in values:
        val = item.strip()
        if _SCOPE_PATTERN.fullmatch(val) is None:
            raise WorkspaceBindingValidationError(
                f"Scope '{val}' in {field_name} is not a valid scope identifier"
            )
        normalized_list.append(val)

    if len(normalized_list) != len(set(normalized_list)):
        raise WorkspaceBindingValidationError(f"{field_name} must not contain duplicate scopes")

    return tuple(sorted(normalized_list))


def _validate_safe_json(mapping: dict[str, Any], field_name: str) -> dict[str, Any]:
    try:
        json.dumps(mapping, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise WorkspaceBindingValidationError(
            f"{field_name} must be JSON serializable"
        ) from exc

    _check_no_secrets(mapping, field_name)
    return dict(sorted(mapping.items()))


def _check_no_secrets(data: Any, field_name: str) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).strip().lower()
            if key_lower in _SECRET_KEYS:
                raise WorkspaceBindingValidationError(
                    f"{field_name} must not contain sensitive key '{key}'"
                )
            _check_no_secrets(value, field_name)
    elif isinstance(data, (list, tuple)):
        for item in data:
            _check_no_secrets(item, field_name)


class BindingStatus(StrEnum):
    """Lifecycle state of a workspace integration binding."""

    active = "active"
    disabled = "disabled"
    pending = "pending"
    error = "error"


class WorkspaceIntegrationBinding(BaseModel):
    """Framework-neutral binding associating a workspace with an external integration."""

    model_config = ConfigDict(frozen=True)

    binding_id: str = Field(
        default_factory=lambda: f"bind-{uuid4().hex[:12]}",
        min_length=2,
        max_length=120,
    )
    workspace_id: str = Field(min_length=2, max_length=120)
    user_id: str = Field(min_length=1, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    status: BindingStatus = BindingStatus.active
    credential: CredentialReference | None = None
    granted_scopes: tuple[str, ...] = Field(default_factory=tuple)
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: str) -> str:
        return _validate_identifier(value, "workspace_id")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _validate_identifier(value, "provider_id")

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _validate_text(value, "user_id")

    @field_validator("granted_scopes")
    @classmethod
    def normalize_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_scopes(value)

    @field_validator("configuration", "metadata")
    @classmethod
    def validate_json_mappings(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_safe_json(value, str(info.field_name))

    @model_validator(mode="after")
    def validate_consistency(self) -> WorkspaceIntegrationBinding:
        if self.credential is not None:
            if self.credential.provider_id != self.provider_id:
                raise WorkspaceBindingValidationError(
                    f"Credential provider '{self.credential.provider_id}' does not match "
                    f"binding provider '{self.provider_id}'"
                )

            if (
                self.credential.ownership.user_id is not None
                and self.credential.ownership.user_id != self.user_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential owner user does not match binding user"
                )

            if (
                self.credential.ownership.workspace_id is not None
                and self.credential.ownership.workspace_id != self.workspace_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential workspace does not match binding workspace"
                )

        return self

    def is_usable(self) -> bool:
        """Report whether this binding is active and its credential is valid for operations."""
        if self.status != BindingStatus.active:
            return False

        if self.credential is not None and self.credential.status != CredentialStatus.active:
            return False

        return True

    def build_integration_request(
        self,
        *,
        request_id: str,
        capability: str,
        correlation_id: str | None = None,
        requested_scopes: tuple[str, ...] | None = None,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IntegrationRequest:
        """Build a typed, validated IntegrationRequest from this active binding."""
        if not self.is_usable():
            raise WorkspaceBindingStateError(
                f"Binding '{self.binding_id}' is in status '{self.status}' and cannot "
                "execute operations"
            )

        scopes_to_request = requested_scopes or self.granted_scopes
        unauthorized_scopes = set(scopes_to_request) - set(self.granted_scopes)
        if unauthorized_scopes:
            raise WorkspaceBindingValidationError(
                f"Requested scopes {sorted(unauthorized_scopes)} exceed granted scopes on binding"
            )

        return IntegrationRequest(
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            provider_id=self.provider_id,
            capability=capability,
            requested_scopes=scopes_to_request,
            credential=self.credential,
            parameters=parameters or {},
            metadata=metadata or {},
        )


class WorkspaceBindingCreate(BaseModel):
    """Payload for creating a new workspace integration binding."""

    model_config = ConfigDict(frozen=True)

    workspace_id: str = Field(min_length=2, max_length=120)
    user_id: str = Field(min_length=1, max_length=128)
    provider_id: str = Field(min_length=2, max_length=120)
    credential: CredentialReference | None = None
    granted_scopes: tuple[str, ...] = Field(default_factory=tuple)
    configuration: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workspace_id", "provider_id")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return _validate_identifier(value, str(info.field_name))

    @field_validator("user_id")
    @classmethod
    def validate_user(cls, value: str) -> str:
        return _validate_text(value, "user_id")

    @field_validator("granted_scopes")
    @classmethod
    def normalize_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_scopes(value)

    @field_validator("configuration", "metadata")
    @classmethod
    def validate_json_mappings(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_safe_json(value, str(info.field_name))


class WorkspaceBindingUpdate(BaseModel):
    """Payload for updating an existing workspace integration binding."""

    model_config = ConfigDict(frozen=True)

    status: BindingStatus | None = None
    credential: CredentialReference | None = None
    granted_scopes: tuple[str, ...] | None = None
    configuration: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("granted_scopes")
    @classmethod
    def normalize_scopes(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return _canonical_scopes(value) if value is not None else None

    @field_validator("configuration", "metadata")
    @classmethod
    def validate_json_mappings(
        cls,
        value: dict[str, Any] | None,
        info: Any,
    ) -> dict[str, Any] | None:
        return _validate_safe_json(value, str(info.field_name)) if value is not None else None


class WorkspaceBindingFilter(BaseModel):
    """Filter parameters for listing and discovering workspace bindings."""

    model_config = ConfigDict(frozen=True)

    workspace_id: str | None = None
    user_id: str | None = None
    provider_id: str | None = None
    status: BindingStatus | None = None
    limit: int | None = Field(default=None, ge=1)
