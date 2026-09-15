"""Domain service for managing workspace integration bindings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domains.workspaces.errors import (
    WorkspaceBindingNotFoundError,
    WorkspaceBindingPermissionError,
    WorkspaceBindingStateError,
    WorkspaceBindingValidationError,
)
from app.domains.workspaces.repository import (
    InMemoryWorkspaceBindingRepository,
    WorkspaceBindingRepository,
)
from app.domains.workspaces.schemas import (
    BindingStatus,
    WorkspaceBindingCreate,
    WorkspaceBindingFilter,
    WorkspaceBindingUpdate,
    WorkspaceIntegrationBinding,
)
from app.integrations.contracts import (
    IntegrationRequest,
    IntegrationStatus,
    ensure_credential_usable,
)
from app.integrations.registry import IntegrationProviderRegistry


class WorkspaceIntegrationService:
    """Coordinates workspace integration bindings with provider discovery and credential bounds."""

    def __init__(
        self,
        repository: WorkspaceBindingRepository | None = None,
        registry: IntegrationProviderRegistry | None = None,
    ) -> None:
        self._repository = repository or InMemoryWorkspaceBindingRepository()
        self._registry = registry

    async def bind_integration(
        self, payload: WorkspaceBindingCreate
    ) -> WorkspaceIntegrationBinding:
        """Create and persist a new workspace integration binding."""
        # Provider validation against registry if configured
        if self._registry is not None:
            provider = self._registry.get(payload.provider_id)
            if provider.metadata.status in (
                IntegrationStatus.disabled,
                IntegrationStatus.unavailable,
            ):
                raise WorkspaceBindingStateError(
                    f"Provider '{payload.provider_id}' is {provider.metadata.status.value} "
                    "and cannot be bound to a workspace"
                )

            # Ensure all required provider permissions are granted
            required_scopes = {s.scope_id for s in provider.metadata.required_permissions}
            missing = sorted(required_scopes - set(payload.granted_scopes))
            if missing:
                raise WorkspaceBindingPermissionError(
                    f"Binding is missing required provider scopes: {', '.join(missing)}"
                )

        # Credential validation
        if payload.credential is not None:
            ensure_credential_usable(payload.credential)
            if payload.credential.provider_id != payload.provider_id:
                raise WorkspaceBindingValidationError(
                    f"Credential provider '{payload.credential.provider_id}' does not match "
                    f"binding provider '{payload.provider_id}'"
                )
            if (
                payload.credential.ownership.user_id is not None
                and payload.credential.ownership.user_id != payload.user_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential owner user does not match binding user"
                )
            if (
                payload.credential.ownership.workspace_id is not None
                and payload.credential.ownership.workspace_id != payload.workspace_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential workspace does not match binding workspace"
                )

        now = datetime.now(UTC)
        binding = WorkspaceIntegrationBinding(
            workspace_id=payload.workspace_id,
            user_id=payload.user_id,
            provider_id=payload.provider_id,
            status=BindingStatus.active,
            credential=payload.credential,
            granted_scopes=payload.granted_scopes,
            configuration=payload.configuration,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )

        return await self._repository.create(binding)

    async def get_binding(
        self,
        binding_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceIntegrationBinding:
        """Retrieve a binding with optional authorization context check."""
        binding = await self._repository.get(binding_id)
        if binding is None:
            raise WorkspaceBindingNotFoundError(f"Binding '{binding_id}' not found")

        if user_id is not None and binding.user_id != user_id:
            raise WorkspaceBindingValidationError("User does not have access to this binding")
        if workspace_id is not None and binding.workspace_id != workspace_id:
            raise WorkspaceBindingValidationError("Workspace does not match binding workspace")

        return binding

    async def get_active_binding(
        self, workspace_id: str, provider_id: str
    ) -> WorkspaceIntegrationBinding:
        """Retrieve the currently active binding for a workspace and provider."""
        binding = await self._repository.get_by_workspace_and_provider(workspace_id, provider_id)
        if binding is None:
            raise WorkspaceBindingNotFoundError(
                f"No active binding found for workspace '{workspace_id}' "
                f"and provider '{provider_id}'"
            )
        return binding

    async def list_bindings(
        self, filters: WorkspaceBindingFilter | None = None
    ) -> tuple[WorkspaceIntegrationBinding, ...]:
        """List bindings matching filter criteria."""
        return await self._repository.list(filters)

    async def disable_binding(
        self, binding_id: str, *, user_id: str | None = None
    ) -> WorkspaceIntegrationBinding:
        """Disable an active workspace binding."""
        binding = await self.get_binding(binding_id, user_id=user_id)
        updated = binding.model_copy(
            update={"status": BindingStatus.disabled, "updated_at": datetime.now(UTC)}
        )
        return await self._repository.update(updated)

    async def enable_binding(
        self, binding_id: str, *, user_id: str | None = None
    ) -> WorkspaceIntegrationBinding:
        """Re-enable a disabled workspace binding after checking provider status."""
        binding = await self.get_binding(binding_id, user_id=user_id)

        if self._registry is not None:
            provider = self._registry.get(binding.provider_id)
            if provider.metadata.status in (
                IntegrationStatus.disabled,
                IntegrationStatus.unavailable,
            ):
                raise WorkspaceBindingStateError(
                    f"Cannot enable binding: Provider '{binding.provider_id}' is "
                    f"{provider.metadata.status.value}"
                )

        if binding.credential is not None:
            ensure_credential_usable(binding.credential)

        updated = binding.model_copy(
            update={"status": BindingStatus.active, "updated_at": datetime.now(UTC)}
        )
        return await self._repository.update(updated)

    async def update_binding(
        self,
        binding_id: str,
        payload: WorkspaceBindingUpdate,
        *,
        user_id: str | None = None,
    ) -> WorkspaceIntegrationBinding:
        """Update configuration, scopes, credential, or status on an existing binding."""
        binding = await self.get_binding(binding_id, user_id=user_id)

        updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}

        if payload.status is not None:
            updates["status"] = payload.status
        if payload.configuration is not None:
            updates["configuration"] = payload.configuration
        if payload.metadata is not None:
            updates["metadata"] = payload.metadata
        if payload.credential is not None:
            ensure_credential_usable(payload.credential)

            if payload.credential.provider_id != binding.provider_id:
                raise WorkspaceBindingValidationError(
                    f"Credential provider '{payload.credential.provider_id}' does not match "
                    f"binding provider '{binding.provider_id}'"
                )

            if (
                payload.credential.ownership is not None
                and payload.credential.ownership.user_id is not None
                and payload.credential.ownership.user_id != binding.user_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential owner user does not match binding user"
                )

            if (
                payload.credential.ownership is not None
                and payload.credential.ownership.workspace_id is not None
                and payload.credential.ownership.workspace_id != binding.workspace_id
            ):
                raise WorkspaceBindingValidationError(
                    "Credential workspace does not match binding workspace"
                )

            updates["credential"] = payload.credential

        if payload.granted_scopes is not None:
            if self._registry is not None:
                provider = self._registry.get(binding.provider_id)
                required_scopes = {s.scope_id for s in provider.metadata.required_permissions}
                missing = sorted(required_scopes - set(payload.granted_scopes))
                if missing:
                    raise WorkspaceBindingPermissionError(
                        f"Updated scopes are missing required provider scopes: {', '.join(missing)}"
                    )
            updates["granted_scopes"] = payload.granted_scopes

        updated_binding = binding.model_copy(update=updates)
        return await self._repository.update(updated_binding)

    async def prepare_integration_request(
        self,
        *,
        workspace_id: str,
        provider_id: str,
        capability: str,
        request_id: str,
        correlation_id: str | None = None,
        requested_scopes: tuple[str, ...] | None = None,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IntegrationRequest:
        """Resolve the active binding and build a validated IntegrationRequest."""
        binding = await self.get_active_binding(workspace_id, provider_id)

        # Registry capability validation if available
        if self._registry is not None:
            if not self._registry.supports(provider_id, capability):
                raise WorkspaceBindingValidationError(
                    f"Provider '{provider_id}' does not support capability '{capability}'"
                )

        return binding.build_integration_request(
            request_id=request_id,
            capability=capability,
            correlation_id=correlation_id,
            requested_scopes=requested_scopes,
            parameters=parameters,
            metadata=metadata,
        )
