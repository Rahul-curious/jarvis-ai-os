from __future__ import annotations

import pytest

from app.integrations import (
    IntegrationCapability,
    IntegrationMetadata,
    IntegrationProvider,
    IntegrationProviderFilter,
    IntegrationProviderRegistry,
    IntegrationRegistryLimits,
    IntegrationRequest,
    IntegrationResponse,
    IntegrationResponseStatus,
    IntegrationStatus,
    ProviderIdentity,
)
from app.integrations.errors import (
    IntegrationProviderNotFoundError,
    IntegrationProviderRegistrationError,
    IntegrationRegistryLimitError,
)


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        *,
        status: IntegrationStatus = IntegrationStatus.available,
        capabilities: tuple[str, ...] = ("read",),
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.metadata = IntegrationMetadata(
            identity=ProviderIdentity(
                provider_id=provider_id,
                display_name=provider_id.title(),
                version="1.0",
            ),
            description=f"Synthetic {provider_id} provider.",
            status=status,
            capabilities=tuple(
                IntegrationCapability(
                    capability_id=capability, description=f"{capability} records."
                )
                for capability in capabilities
            ),
            metadata=metadata or {},
        )
        self.execute_calls = 0

    def supports_capability(self, capability: str) -> bool:
        return any(item.capability_id == capability for item in self.metadata.capabilities)

    async def execute(self, request: IntegrationRequest) -> IntegrationResponse:
        self.execute_calls += 1
        return IntegrationResponse(
            request_id=request.request_id,
            provider_id=request.provider_id,
            capability=request.capability,
            status=IntegrationResponseStatus.succeeded,
        )


class InvalidMetadataProvider:
    metadata = {"safe": "value"}

    def supports_capability(self, capability: str) -> bool:
        return False

    async def execute(self, request: IntegrationRequest) -> IntegrationResponse:
        raise AssertionError("registry must not execute providers")


def test_registration_is_explicit_validated_and_does_not_execute_providers() -> None:
    provider = FakeProvider("zulu")
    registry = IntegrationProviderRegistry()

    registered = registry.register(provider)

    assert registered.identity.provider_id == "zulu"
    assert registry.count == 1
    assert provider.execute_calls == 0

    with pytest.raises(IntegrationProviderRegistrationError):
        registry.register(provider)
    with pytest.raises(IntegrationProviderRegistrationError):
        registry.register(object())  # type: ignore[arg-type]
    assert provider.execute_calls == 0


def test_lookup_and_unregister_are_typed_and_do_not_execute_providers() -> None:
    provider = FakeProvider("example")
    registry = IntegrationProviderRegistry([provider])

    assert registry.get("example") is provider
    assert provider.execute_calls == 0

    removed = registry.unregister("example")
    assert removed.identity.provider_id == "example"
    assert registry.count == 0

    with pytest.raises(IntegrationProviderNotFoundError):
        registry.get("missing")
    with pytest.raises(IntegrationProviderNotFoundError):
        registry.unregister("missing")


def test_discovery_filters_status_and_capability_with_stable_ordering() -> None:
    providers = [
        FakeProvider("zulu", capabilities=("read", "search")),
        FakeProvider("alpha", capabilities=("read",)),
        FakeProvider("bravo", status=IntegrationStatus.degraded, capabilities=("search",)),
        FakeProvider("disabled", status=IntegrationStatus.disabled),
        FakeProvider("offline", status=IntegrationStatus.unavailable),
    ]
    registry = IntegrationProviderRegistry(providers)

    assert [item.identity.provider_id for item in registry.list()] == [
        "alpha",
        "bravo",
        "zulu",
    ]
    assert [item.identity.provider_id for item in registry.find(capability="search")] == [
        "bravo",
        "zulu",
    ]
    assert [
        item.identity.provider_id
        for item in registry.find(
            status=IntegrationStatus.disabled,
            include_unavailable=True,
        )
    ] == ["disabled"]
    assert [item.identity.provider_id for item in registry.find(include_unavailable=True)] == [
        "alpha",
        "bravo",
        "disabled",
        "offline",
        "zulu",
    ]
    assert registry.supports("zulu", "search") is True
    assert registry.supports("zulu", "delete") is False

    for provider in providers:
        assert provider.execute_calls == 0


def test_discovery_limits_and_empty_registry_are_explicit() -> None:
    registry = IntegrationProviderRegistry(
        limits=IntegrationRegistryLimits(max_providers=2, max_discovery_results=1)
    )
    assert registry.list() == ()

    registry.register(FakeProvider("alpha"))
    registry.register(FakeProvider("bravo"))
    with pytest.raises(IntegrationRegistryLimitError):
        registry.register(FakeProvider("charlie"))
    with pytest.raises(IntegrationRegistryLimitError):
        registry.find(limit=2)
    assert len(registry.find()) == 1


def test_filter_model_and_metadata_are_validated_without_network_calls() -> None:
    assert IntegrationProviderFilter(provider_id=" example ").provider_id == "example"
    with pytest.raises(ValueError):
        IntegrationProviderFilter(capability="Search")

    registry = IntegrationProviderRegistry()
    with pytest.raises(IntegrationProviderRegistrationError):
        registry.register(FakeProvider("secret", metadata={"nested": {"api_key": "synthetic"}}))
    with pytest.raises(IntegrationProviderRegistrationError):
        registry.register(InvalidMetadataProvider())


def test_provider_metadata_is_exposed_as_contract_data_only() -> None:
    provider = FakeProvider("example", metadata={"region": "test"})
    registry = IntegrationProviderRegistry([provider])

    metadata = registry.find(provider_id="example")[0]

    assert metadata.identity.provider_id == "example"
    assert metadata.metadata == {"region": "test"}
    assert "access_token" not in metadata.model_dump()
    assert "refresh_token" not in metadata.model_dump()


def test_package_exports_registry_contracts() -> None:
    assert IntegrationProviderRegistry.__module__ == "app.integrations.registry"
    assert IntegrationProvider.__name__ == "IntegrationProvider"
