"""Comprehensive test suite for Phase 7.5 Workspace Integration Binding."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.domains.workspaces import (
    BindingStatus,
    InMemoryWorkspaceBindingRepository,
    WorkspaceBindingCreate,
    WorkspaceBindingDuplicateError,
    WorkspaceBindingFilter,
    WorkspaceBindingNotFoundError,
    WorkspaceBindingPermissionError,
    WorkspaceBindingStateError,
    WorkspaceBindingUpdate,
    WorkspaceBindingValidationError,
    WorkspaceIntegrationBinding,
    WorkspaceIntegrationService,
)
from app.integrations import (
    CredentialOwnership,
    CredentialReference,
    CredentialStatus,
    CredentialType,
    IntegrationCapability,
    IntegrationMetadata,
    IntegrationProviderRegistry,
    IntegrationResponse,
    IntegrationResponseStatus,
    IntegrationStatus,
    PermissionRisk,
    PermissionScope,
    ProviderIdentity,
)
from app.integrations.github import GitHubProvider


def _credential(**overrides: Any) -> CredentialReference:
    values: dict[str, Any] = {
        "provider_id": "github",
        "reference_id": "vault://credentials/github/user-001",
        "credential_type": CredentialType.oauth2,
        "ownership": CredentialOwnership(user_id="user-001", workspace_id="workspace-001"),
        "granted_scopes": ("repo:read",),
        "status": CredentialStatus.active,
    }
    values.update(overrides)
    return CredentialReference(**values)


def _binding_create(**overrides: Any) -> WorkspaceBindingCreate:
    values: dict[str, Any] = {
        "workspace_id": "workspace-001",
        "user_id": "user-001",
        "provider_id": "github",
        "credential": _credential(),
        "granted_scopes": ("repo:read",),
        "configuration": {"default_branch": "main"},
        "metadata": {"source": "unit_test"},
    }
    values.update(overrides)
    return WorkspaceBindingCreate(**values)


class FakeProvider:
    """Synthetic provider for testing binding validation."""

    def __init__(
        self,
        provider_id: str = "example_provider",
        *,
        status: IntegrationStatus = IntegrationStatus.available,
        required_scopes: tuple[str, ...] = ("records.read",),
        capabilities: tuple[str, ...] = ("read",),
    ) -> None:
        self.metadata = IntegrationMetadata(
            identity=ProviderIdentity(
                provider_id=provider_id,
                display_name=provider_id.title(),
                version="1.0",
            ),
            description="Synthetic provider for testing.",
            status=status,
            capabilities=tuple(
                IntegrationCapability(
                    capability_id=cap, description=f"Capability {cap}"
                )
                for cap in capabilities
            ),
            required_permissions=tuple(
                PermissionScope(
                    provider_id=provider_id,
                    scope_id=scope,
                    description=f"Scope {scope}",
                    risk=PermissionRisk.low,
                )
                for scope in required_scopes
            ),
        )

    def supports_capability(self, capability: str) -> bool:
        return any(item.capability_id == capability for item in self.metadata.capabilities)

    async def execute(self, request: Any) -> IntegrationResponse:
        return IntegrationResponse(
            request_id=request.request_id,
            provider_id=request.provider_id,
            capability=request.capability,
            status=IntegrationResponseStatus.succeeded,
        )


def test_workspace_binding_model_validates_consistency_and_rejects_secrets() -> None:
    # Valid binding
    binding = WorkspaceIntegrationBinding(
        workspace_id="workspace-001",
        user_id="user-001",
        provider_id="github",
        credential=_credential(),
        granted_scopes=("repo:read",),
        configuration={"setting": "val"},
    )
    assert binding.is_usable() is True
    assert binding.workspace_id == "workspace-001"
    assert binding.provider_id == "github"

    # Secret field rejection in configuration
    with pytest.raises(WorkspaceBindingValidationError, match="sensitive key 'access_token'"):
        WorkspaceIntegrationBinding(
            workspace_id="workspace-001",
            user_id="user-001",
            provider_id="github",
            configuration={"access_token": "secret123"},
        )

    with pytest.raises(WorkspaceBindingValidationError, match="sensitive key 'secret'"):
        WorkspaceIntegrationBinding(
            workspace_id="workspace-001",
            user_id="user-001",
            provider_id="github",
            metadata={"nested": {"secret": "val"}},
        )

    # Credential provider mismatch
    with pytest.raises(WorkspaceBindingValidationError, match="Credential provider"):
        WorkspaceIntegrationBinding(
            workspace_id="workspace-001",
            user_id="user-001",
            provider_id="github",
            credential=_credential(provider_id="slack", granted_scopes=()),
        )

    # Credential owner user mismatch
    with pytest.raises(WorkspaceBindingValidationError, match="Credential owner user"):
        WorkspaceIntegrationBinding(
            workspace_id="workspace-001",
            user_id="user-001",
            provider_id="github",
            credential=_credential(
                ownership=CredentialOwnership(user_id="user-999", workspace_id="workspace-001")
            ),
        )

    # Credential workspace mismatch
    with pytest.raises(WorkspaceBindingValidationError, match="Credential workspace"):
        WorkspaceIntegrationBinding(
            workspace_id="workspace-001",
            user_id="user-001",
            provider_id="github",
            credential=_credential(
                ownership=CredentialOwnership(user_id="user-001", workspace_id="workspace-999")
            ),
        )


def test_build_integration_request_from_binding() -> None:
    binding = WorkspaceIntegrationBinding(
        workspace_id="workspace-001",
        user_id="user-001",
        provider_id="github",
        credential=_credential(),
        granted_scopes=("issues:read", "repo:read"),
    )

    req = binding.build_integration_request(
        request_id="req-100",
        capability="repos.get",
        requested_scopes=("repo:read",),
        parameters={"owner": "octocat"},
    )
    assert req.request_id == "req-100"
    assert req.workspace_id == "workspace-001"
    assert req.user_id == "user-001"
    assert req.provider_id == "github"
    assert req.capability == "repos.get"
    assert req.requested_scopes == ("repo:read",)

    # Scope escalation rejection
    with pytest.raises(WorkspaceBindingValidationError, match="exceed granted scopes"):
        binding.build_integration_request(
            request_id="req-101",
            capability="repos.get",
            requested_scopes=("admin:all",),
        )

    # Disabled binding rejection
    disabled_binding = binding.model_copy(update={"status": BindingStatus.disabled})
    assert disabled_binding.is_usable() is False
    with pytest.raises(WorkspaceBindingStateError, match="cannot execute operations"):
        disabled_binding.build_integration_request(
            request_id="req-102", capability="repos.get"
        )


def test_in_memory_repository_crud_and_duplicate_prevention() -> None:
    repo = InMemoryWorkspaceBindingRepository()

    b1 = WorkspaceIntegrationBinding(
        workspace_id="ws-a",
        user_id="user-1",
        provider_id="github",
    )

    created = asyncio.run(repo.create(b1))
    assert created.binding_id == b1.binding_id
    assert asyncio.run(repo.count()) == 1

    # Duplicate active binding for same workspace + provider
    b_dup = WorkspaceIntegrationBinding(
        workspace_id="ws-a",
        user_id="user-2",
        provider_id="github",
    )
    with pytest.raises(WorkspaceBindingDuplicateError, match="An active binding already exists"):
        asyncio.run(repo.create(b_dup))

    # Binding for different provider allowed
    b_slack = WorkspaceIntegrationBinding(
        workspace_id="ws-a",
        user_id="user-1",
        provider_id="slack",
    )
    asyncio.run(repo.create(b_slack))
    assert asyncio.run(repo.count()) == 2

    # Get by workspace and provider
    retrieved = asyncio.run(repo.get_by_workspace_and_provider("ws-a", "github"))
    assert retrieved is not None
    assert retrieved.binding_id == b1.binding_id

    # Update
    updated = b1.model_copy(update={"status": BindingStatus.disabled})
    asyncio.run(repo.update(updated))

    # Now duplicate active binding creation is allowed since b1 is disabled
    asyncio.run(repo.create(b_dup))

    # Delete
    deleted = asyncio.run(repo.delete(b_dup.binding_id))
    assert deleted is True


def test_service_bind_integration_with_registry_and_scope_validation() -> None:
    registry = IntegrationProviderRegistry()
    registry.register(GitHubProvider())

    service = WorkspaceIntegrationService(registry=registry)

    # Successful creation
    create_payload = _binding_create(granted_scopes=("repo:read",))
    binding = asyncio.run(service.bind_integration(create_payload))

    assert binding.workspace_id == "workspace-001"
    assert binding.provider_id == "github"
    assert binding.status == BindingStatus.active

    # Missing required scopes rejection
    bad_scopes_payload = _binding_create(
        workspace_id="workspace-002",
        granted_scopes=(),  # GitHub requires repo:read
    )
    with pytest.raises(WorkspaceBindingPermissionError, match="missing required provider scopes"):
        asyncio.run(service.bind_integration(bad_scopes_payload))

    # Unavailable provider rejection
    registry.register(FakeProvider("disabled_provider", status=IntegrationStatus.disabled))
    disabled_payload = WorkspaceBindingCreate(
        workspace_id="workspace-003",
        user_id="user-001",
        provider_id="disabled_provider",
    )
    with pytest.raises(WorkspaceBindingStateError, match="cannot be bound"):
        asyncio.run(service.bind_integration(disabled_payload))


def test_service_lifecycle_enable_disable_and_update() -> None:
    registry = IntegrationProviderRegistry()
    fake_prov = FakeProvider("example", required_scopes=("records.read",))
    registry.register(fake_prov)

    service = WorkspaceIntegrationService(registry=registry)

    payload = WorkspaceBindingCreate(
        workspace_id="ws-10",
        user_id="usr-10",
        provider_id="example",
        granted_scopes=("records.read",),
    )
    binding = asyncio.run(service.bind_integration(payload))
    assert binding.status == BindingStatus.active

    # Disable
    disabled = asyncio.run(service.disable_binding(binding.binding_id, user_id="usr-10"))
    assert disabled.status == BindingStatus.disabled

    # Enable
    enabled = asyncio.run(service.enable_binding(binding.binding_id, user_id="usr-10"))
    assert enabled.status == BindingStatus.active

    # Update configuration
    updated = asyncio.run(
        service.update_binding(
            binding.binding_id,
            WorkspaceBindingUpdate(configuration={"key": "val"}),
            user_id="usr-10",
        )
    )
    assert updated.configuration == {"key": "val"}

    # Reject a credential whose provider does not match the binding.
    with pytest.raises(
        WorkspaceBindingValidationError, match="Credential provider"
    ):
        asyncio.run(
            service.update_binding(
                binding.binding_id,
                WorkspaceBindingUpdate(
                    credential=CredentialReference(
                        provider_id="other-provider",
                        reference_id="vault://credentials/other",
                        credential_type=CredentialType.oauth2,
                        ownership=CredentialOwnership(
                            user_id="usr-10",
                            workspace_id="ws-10",
                        ),
                    )
                ),
                user_id="usr-10",
            )
        )

    # Unauthorized user access
    with pytest.raises(WorkspaceBindingValidationError, match="User does not have access"):
        asyncio.run(service.get_binding(binding.binding_id, user_id="wrong-user"))

    # Not found error
    with pytest.raises(WorkspaceBindingNotFoundError, match="not found"):
        asyncio.run(service.get_binding("non-existent-binding"))


def test_service_prepare_integration_request() -> None:
    registry = IntegrationProviderRegistry()
    registry.register(GitHubProvider())

    service = WorkspaceIntegrationService(registry=registry)

    payload = _binding_create(granted_scopes=("repo:read",))
    asyncio.run(service.bind_integration(payload))

    req = asyncio.run(
        service.prepare_integration_request(
            workspace_id="workspace-001",
            provider_id="github",
            capability="repos.get",
            request_id="req-500",
            parameters={"owner": "octocat", "repo": "Hello-World"},
        )
    )

    assert req.request_id == "req-500"
    assert req.provider_id == "github"
    assert req.capability == "repos.get"

    # Capability unsupported rejection
    with pytest.raises(WorkspaceBindingValidationError, match="does not support capability"):
        asyncio.run(
            service.prepare_integration_request(
                workspace_id="workspace-001",
                provider_id="github",
                capability="unsupported.cap",
                request_id="req-501",
            )
        )


def test_github_provider_phase_7_4_compatibility() -> None:
    """Verify that a bound GitHub integration seamlessly executes through GitHubProvider."""
    registry = IntegrationProviderRegistry()
    github_provider = GitHubProvider()
    registry.register(github_provider)

    service = WorkspaceIntegrationService(registry=registry)

    cred = _credential(
        ownership=CredentialOwnership(user_id="octocat-user", workspace_id="acme-workspace")
    )
    payload = _binding_create(
        workspace_id="acme-workspace",
        user_id="octocat-user",
        provider_id="github",
        credential=cred,
        granted_scopes=("repo:read",),
    )
    binding = asyncio.run(service.bind_integration(payload))
    assert binding.is_usable() is True

    # Prepare an integration request from workspace binding
    req = asyncio.run(
        service.prepare_integration_request(
            workspace_id="acme-workspace",
            provider_id="github",
            capability="user.get",
            request_id="req-exec-001",
        )
    )

    # Provider executes request cleanly without errors
    response = asyncio.run(github_provider.execute(req))
    assert response.request_id == "req-exec-001"
    assert response.provider_id == "github"
    assert response.capability == "user.get"


def test_workspace_binding_discovery_filtering() -> None:
    repo = InMemoryWorkspaceBindingRepository()

    b1 = WorkspaceIntegrationBinding(
        workspace_id="ws-1", user_id="u-1", provider_id="github", status=BindingStatus.active
    )
    b2 = WorkspaceIntegrationBinding(
        workspace_id="ws-1", user_id="u-1", provider_id="slack", status=BindingStatus.disabled
    )
    b3 = WorkspaceIntegrationBinding(
        workspace_id="ws-2", user_id="u-2", provider_id="github", status=BindingStatus.active
    )

    asyncio.run(repo.create(b1))
    asyncio.run(repo.create(b2))
    asyncio.run(repo.create(b3))

    # Filter by workspace_id
    ws1_bindings = asyncio.run(repo.list(WorkspaceBindingFilter(workspace_id="ws-1")))
    assert len(ws1_bindings) == 2

    # Filter by provider_id
    gh_bindings = asyncio.run(repo.list(WorkspaceBindingFilter(provider_id="github")))
    assert len(gh_bindings) == 2

    # Filter by status
    active_bindings = asyncio.run(repo.list(WorkspaceBindingFilter(status=BindingStatus.active)))
    assert len(active_bindings) == 2
