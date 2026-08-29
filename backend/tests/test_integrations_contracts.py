from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from app.integrations import (
    CredentialReference,
    CredentialType,
    IntegrationCapability,
    IntegrationErrorInfo,
    IntegrationMetadata,
    IntegrationProvider,
    IntegrationRequest,
    IntegrationResponse,
    IntegrationResponseStatus,
    IntegrationStatus,
    PermissionRisk,
    PermissionScope,
    ProviderIdentity,
    validate_provider_request,
)
from app.integrations.errors import (
    IntegrationCapabilityError,
    IntegrationConfigurationError,
    IntegrationCredentialError,
    IntegrationPermissionError,
    IntegrationProviderUnavailableError,
    IntegrationValidationError,
)


def _provider_metadata(
    *,
    status: IntegrationStatus = IntegrationStatus.available,
) -> IntegrationMetadata:
    return IntegrationMetadata(
        identity=ProviderIdentity(
            provider_id="example_provider",
            display_name="Example Provider",
            version="1.0",
        ),
        description="Provider used to verify the generic integration boundary.",
        status=status,
        capabilities=(
            IntegrationCapability(capability_id="search", description="Search records."),
            IntegrationCapability(capability_id="read", description="Read records."),
        ),
        required_permissions=(
            PermissionScope(
                provider_id="example_provider",
                scope_id="records.read",
                description="Read provider records.",
                risk=PermissionRisk.medium,
            ),
        ),
        metadata={"region": "test", "version": 1},
    )


class FakeProvider:
    def __init__(self, metadata: IntegrationMetadata | None = None) -> None:
        self.metadata = metadata or _provider_metadata()
        self.executed = False

    def supports_capability(self, capability: str) -> bool:
        return any(item.capability_id == capability for item in self.metadata.capabilities)

    async def execute(self, request: IntegrationRequest) -> IntegrationResponse:
        self.executed = True
        return IntegrationResponse(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            provider_id=request.provider_id,
            capability=request.capability,
            status=IntegrationResponseStatus.succeeded,
            result={"items": []},
            metadata={"provider_version": self.metadata.identity.version},
        )


def _request(**overrides: Any) -> IntegrationRequest:
    values: dict[str, Any] = {
        "request_id": "request-001",
        "correlation_id": "trace-001",
        "user_id": "user-001",
        "workspace_id": "workspace-001",
        "provider_id": "example_provider",
        "capability": "read",
        "requested_scopes": ("records.read",),
        "parameters": {"limit": 10},
        "metadata": {"source": "test"},
    }
    values.update(overrides)
    return IntegrationRequest(**values)


def test_provider_contract_is_async_and_runtime_checkable() -> None:
    provider = FakeProvider()

    assert isinstance(provider, IntegrationProvider)
    assert inspect.iscoroutinefunction(provider.execute)

    response = asyncio.run(provider.execute(_request()))

    assert response.status is IntegrationResponseStatus.succeeded
    assert provider.executed is True


def test_metadata_is_deterministic_and_rejects_duplicate_capabilities() -> None:
    metadata = _provider_metadata()

    assert tuple(item.capability_id for item in metadata.capabilities) == ("read", "search")
    assert tuple(item.scope_id for item in metadata.required_permissions) == ("records.read",)
    assert tuple(metadata.metadata) == ("region", "version")

    with pytest.raises(IntegrationConfigurationError):
        IntegrationMetadata(
            identity=metadata.identity,
            description=metadata.description,
            capabilities=metadata.capabilities
            + (IntegrationCapability(capability_id="read", description="Duplicate."),),
        )


def test_permission_scope_and_capability_identifiers_are_validated() -> None:
    with pytest.raises(ValidationError):
        IntegrationCapability(capability_id="Read", description="Invalid identifier.")

    with pytest.raises(ValidationError):
        PermissionScope(
            provider_id="example_provider",
            scope_id="not a scope",
            description="Invalid scope.",
        )

    with pytest.raises(ValidationError):
        IntegrationRequest(
            request_id="request-001",
            user_id="user-001",
            provider_id="example_provider",
            capability="read",
            requested_scopes=("records.read", "records.read"),
        )


def test_credential_reference_is_opaque_and_rejects_secret_metadata() -> None:
    credential = CredentialReference(
        provider_id="example_provider",
        reference_id="vault://credentials/example-provider/default",
        credential_type=CredentialType.oauth2,
        metadata={"label": "default", "rotation_epoch": 3},
    )

    assert "access_token" not in credential.model_dump()
    assert credential.metadata == {"label": "default", "rotation_epoch": 3}

    with pytest.raises(IntegrationCredentialError):
        CredentialReference(
            provider_id="example_provider",
            reference_id="vault://credentials/example-provider/default",
            credential_type=CredentialType.oauth2,
            metadata={"access_token": "plaintext-secret"},
        )


def test_request_and_response_validate_identity_payload_and_result_state() -> None:
    request = _request(parameters={"limit": 10}, metadata={"b": 2, "a": 1})
    assert tuple(request.parameters) == ("limit",)
    assert tuple(request.metadata) == ("a", "b")

    with pytest.raises(ValidationError):
        _request(metadata={"invalid": float("nan")})

    with pytest.raises(IntegrationValidationError):
        IntegrationResponse(
            request_id=request.request_id,
            provider_id=request.provider_id,
            capability=request.capability,
            status=IntegrationResponseStatus.succeeded,
            error=IntegrationErrorInfo(code="provider_error", message="Unexpected failure."),
        )

    with pytest.raises(IntegrationValidationError):
        IntegrationResponse(
            request_id=request.request_id,
            provider_id=request.provider_id,
            capability=request.capability,
            status=IntegrationResponseStatus.failed,
        )


def test_provider_request_validation_checks_capability_permissions_and_identity() -> None:
    provider = FakeProvider()

    validate_provider_request(provider, _request())

    with pytest.raises(IntegrationCapabilityError):
        validate_provider_request(provider, _request(capability="delete"))

    with pytest.raises(IntegrationPermissionError):
        validate_provider_request(provider, _request(requested_scopes=()))

    with pytest.raises(IntegrationValidationError):
        validate_provider_request(provider, _request(provider_id="other_provider"))

    with pytest.raises(IntegrationProviderUnavailableError):
        validate_provider_request(
            FakeProvider(metadata=_provider_metadata(status=IntegrationStatus.disabled)),
            _request(),
        )


def test_package_exports_are_available_without_infrastructure_dependencies() -> None:
    assert IntegrationProvider.__module__ == "app.integrations.contracts"
    assert validate_provider_request.__module__ == "app.integrations.contracts"
