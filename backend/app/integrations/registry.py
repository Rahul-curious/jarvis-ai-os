"""Instance-scoped registry for framework-neutral integration providers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.contracts import (
    IntegrationMetadata,
    IntegrationProvider,
    IntegrationStatus,
)
from app.integrations.errors import (
    IntegrationProviderNotFoundError,
    IntegrationProviderRegistrationError,
    IntegrationRegistryLimitError,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_SECRET_METADATA_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "client_secret",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)


class IntegrationRegistryLimits(BaseModel):
    """Operational bounds for an in-memory provider registry."""

    model_config = ConfigDict(frozen=True)

    max_providers: int = Field(default=256, ge=1)
    max_discovery_results: int = Field(default=128, ge=1)


class IntegrationProviderFilter(BaseModel):
    """Explicit, provider-neutral discovery filters."""

    model_config = ConfigDict(frozen=True)

    provider_id: str | None = Field(default=None, min_length=2, max_length=120)
    capability: str | None = Field(default=None, min_length=2, max_length=120)
    status: IntegrationStatus | None = None
    include_unavailable: bool = False
    limit: int | None = Field(default=None, ge=1)

    @field_validator("provider_id", "capability")
    @classmethod
    def validate_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
            raise ValueError("provider filters must use lowercase stable identifiers")
        return normalized


class IntegrationProviderRegistry:
    """Explicit registry that discovers providers without executing them."""

    def __init__(
        self,
        providers: Iterable[IntegrationProvider] = (),
        *,
        limits: IntegrationRegistryLimits | None = None,
    ) -> None:
        self.limits = limits or IntegrationRegistryLimits()
        self._providers: dict[str, IntegrationProvider] = {}
        for provider in providers:
            self.register(provider)

    @property
    def count(self) -> int:
        """Return the number of explicitly registered providers."""

        return len(self._providers)

    def register(self, provider: IntegrationProvider) -> IntegrationMetadata:
        """Validate and register a provider without invoking provider operations."""

        metadata = self._validate_provider(provider)
        provider_id = metadata.identity.provider_id
        if provider_id in self._providers:
            raise IntegrationProviderRegistrationError(
                f"provider is already registered: {provider_id}"
            )
        if self.count >= self.limits.max_providers:
            raise IntegrationRegistryLimitError("provider registry has reached its maximum size")
        self._providers[provider_id] = provider
        return metadata

    def unregister(self, provider_id: str) -> IntegrationMetadata:
        """Remove and return one provider's metadata."""

        provider = self._providers.pop(self._validate_provider_id(provider_id), None)
        if provider is None:
            raise IntegrationProviderNotFoundError(f"provider is not registered: {provider_id}")
        return provider.metadata

    def get(self, provider_id: str) -> IntegrationProvider:
        """Return a registered provider or raise a typed lookup error."""

        normalized_id = self._validate_provider_id(provider_id)
        provider = self._providers.get(normalized_id)
        if provider is None:
            raise IntegrationProviderNotFoundError(f"provider is not registered: {provider_id}")
        return provider

    def list(
        self, filters: IntegrationProviderFilter | None = None
    ) -> tuple[IntegrationMetadata, ...]:
        """List provider metadata using deterministic filtering and ordering."""

        return self.discover(filters=filters)

    def discover(
        self,
        *,
        filters: IntegrationProviderFilter | None = None,
    ) -> tuple[IntegrationMetadata, ...]:
        """Discover providers by metadata without invoking provider operations."""

        discovery = filters or IntegrationProviderFilter()
        limit = self._resolve_limit(discovery.limit)
        results = [
            provider.metadata
            for provider in sorted(
                self._providers.values(),
                key=lambda registered: registered.metadata.identity.provider_id,
            )
            if self._matches(provider.metadata, discovery)
        ]
        return tuple(results[:limit])

    def find(
        self,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
        status: IntegrationStatus | None = None,
        include_unavailable: bool = False,
        limit: int | None = None,
    ) -> tuple[IntegrationMetadata, ...]:
        """Convenience discovery method for common registry filters."""

        return self.discover(
            filters=IntegrationProviderFilter(
                provider_id=provider_id,
                capability=capability,
                status=status,
                include_unavailable=include_unavailable,
                limit=limit,
            )
        )

    def supports(self, provider_id: str, capability: str) -> bool:
        """Return whether a registered provider advertises a capability."""

        provider = self.get(provider_id)
        normalized_capability = IntegrationProviderFilter(capability=capability).capability
        return any(
            item.capability_id == normalized_capability for item in provider.metadata.capabilities
        )

    def providers(self) -> tuple[IntegrationProvider, ...]:
        """Return registered provider objects ordered by stable provider ID."""

        return tuple(
            sorted(
                self._providers.values(),
                key=lambda provider: provider.metadata.identity.provider_id,
            )
        )

    def _validate_provider(self, provider: IntegrationProvider) -> IntegrationMetadata:
        if not isinstance(provider, IntegrationProvider):
            raise IntegrationProviderRegistrationError(
                "provider must implement the IntegrationProvider protocol"
            )
        try:
            metadata = provider.metadata
        except Exception as exc:
            raise IntegrationProviderRegistrationError(
                "provider metadata could not be read"
            ) from exc
        if not isinstance(metadata, IntegrationMetadata):
            raise IntegrationProviderRegistrationError(
                "provider metadata must be an IntegrationMetadata instance"
            )
        self._validate_safe_metadata(metadata)
        return metadata

    def _validate_provider_id(self, provider_id: str) -> str:
        normalized = provider_id.strip()
        if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
            raise IntegrationProviderRegistrationError(
                "provider_id must be a lowercase stable identifier"
            )
        return normalized

    def _resolve_limit(self, requested_limit: int | None) -> int:
        limit = requested_limit or self.limits.max_discovery_results
        if limit > self.limits.max_discovery_results:
            raise IntegrationRegistryLimitError("discovery limit exceeds the registry maximum")
        return limit

    @staticmethod
    def _matches(
        metadata: IntegrationMetadata,
        filters: IntegrationProviderFilter,
    ) -> bool:
        status_is_unavailable = metadata.status in {
            IntegrationStatus.disabled,
            IntegrationStatus.unavailable,
        }
        if status_is_unavailable and not filters.include_unavailable:
            return False
        if filters.provider_id is not None and metadata.identity.provider_id != filters.provider_id:
            return False
        if filters.status is not None and metadata.status != filters.status:
            return False
        if filters.capability is not None and not any(
            capability.capability_id == filters.capability for capability in metadata.capabilities
        ):
            return False
        return True

    @classmethod
    def _validate_safe_metadata(cls, metadata: IntegrationMetadata) -> None:
        try:
            json.dumps(metadata.metadata, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise IntegrationProviderRegistrationError(
                "provider metadata must be JSON serializable"
            ) from exc
        if cls._contains_secret_field(metadata.metadata):
            raise IntegrationProviderRegistrationError(
                "provider metadata must not contain credential material"
            )

    @staticmethod
    def _contains_secret_field(value: Any) -> bool:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in _SECRET_METADATA_KEYS or normalized_key in {
                    "private_key",
                    "credential",
                }:
                    return True
                if IntegrationProviderRegistry._contains_secret_field(nested_value):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(IntegrationProviderRegistry._contains_secret_field(item) for item in value)
        return False
