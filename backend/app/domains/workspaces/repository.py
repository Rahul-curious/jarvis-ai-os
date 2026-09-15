"""Repository boundary and in-memory implementation for workspace integration bindings."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from app.domains.workspaces.errors import (
    WorkspaceBindingDuplicateError,
    WorkspaceBindingNotFoundError,
)
from app.domains.workspaces.schemas import (
    BindingStatus,
    WorkspaceBindingFilter,
    WorkspaceIntegrationBinding,
)


@runtime_checkable
class WorkspaceBindingRepository(Protocol):
    """Async repository protocol for storing and retrieving workspace integration bindings."""

    async def create(self, binding: WorkspaceIntegrationBinding) -> WorkspaceIntegrationBinding:
        """Persist a new workspace integration binding."""

    async def get(self, binding_id: str) -> WorkspaceIntegrationBinding | None:
        """Retrieve a binding by its unique identifier."""

    async def get_by_workspace_and_provider(
        self, workspace_id: str, provider_id: str
    ) -> WorkspaceIntegrationBinding | None:
        """Retrieve the active binding for a given workspace and provider."""

    async def list(
        self, filters: WorkspaceBindingFilter | None = None
    ) -> tuple[WorkspaceIntegrationBinding, ...]:
        """List bindings matching filter criteria with deterministic ordering."""

    async def update(self, binding: WorkspaceIntegrationBinding) -> WorkspaceIntegrationBinding:
        """Update an existing workspace integration binding."""

    async def delete(self, binding_id: str) -> bool:
        """Remove a binding by its unique identifier."""

    async def count(self) -> int:
        """Return the total number of bindings."""


class InMemoryWorkspaceBindingRepository(WorkspaceBindingRepository):
    """In-memory, async-compatible repository for workspace integration bindings."""

    def __init__(self, max_records: int = 1000) -> None:
        self.max_records = max_records
        self._records: dict[str, WorkspaceIntegrationBinding] = {}
        self._lock = asyncio.Lock()

    async def count(self) -> int:
        async with self._lock:
            return len(self._records)

    async def create(self, binding: WorkspaceIntegrationBinding) -> WorkspaceIntegrationBinding:
        async with self._lock:
            if binding.binding_id in self._records:
                raise WorkspaceBindingDuplicateError(
                    f"Binding with ID '{binding.binding_id}' already exists"
                )

            # Prevent duplicate active bindings for the same workspace + provider
            if binding.status == BindingStatus.active:
                for existing in self._records.values():
                    if (
                        existing.workspace_id == binding.workspace_id
                        and existing.provider_id == binding.provider_id
                        and existing.status == BindingStatus.active
                    ):
                        raise WorkspaceBindingDuplicateError(
                            f"An active binding already exists for workspace "
                            f"'{binding.workspace_id}' and provider '{binding.provider_id}'"
                        )

            if len(self._records) >= self.max_records:
                raise WorkspaceBindingDuplicateError("Workspace binding storage limit exceeded")

            self._records[binding.binding_id] = binding
            return binding

    async def get(self, binding_id: str) -> WorkspaceIntegrationBinding | None:
        async with self._lock:
            return self._records.get(binding_id)

    async def get_by_workspace_and_provider(
        self, workspace_id: str, provider_id: str
    ) -> WorkspaceIntegrationBinding | None:
        async with self._lock:
            for b in self._records.values():
                if (
                    b.workspace_id == workspace_id
                    and b.provider_id == provider_id
                    and b.status == BindingStatus.active
                ):
                    return b
            return None

    async def list(
        self, filters: WorkspaceBindingFilter | None = None
    ) -> tuple[WorkspaceIntegrationBinding, ...]:
        async with self._lock:
            f = filters or WorkspaceBindingFilter()
            results = [
                b
                for b in sorted(self._records.values(), key=lambda x: x.binding_id)
                if self._matches(b, f)
            ]
            if f.limit is not None:
                results = results[: f.limit]
            return tuple(results)

    async def update(self, binding: WorkspaceIntegrationBinding) -> WorkspaceIntegrationBinding:
        async with self._lock:
            if binding.binding_id not in self._records:
                raise WorkspaceBindingNotFoundError(
                    f"Binding with ID '{binding.binding_id}' does not exist"
                )

            # Check duplicate active bindings
            if binding.status == BindingStatus.active:
                for existing in self._records.values():
                    if (
                        existing.binding_id != binding.binding_id
                        and existing.workspace_id == binding.workspace_id
                        and existing.provider_id == binding.provider_id
                        and existing.status == BindingStatus.active
                    ):
                        raise WorkspaceBindingDuplicateError(
                            f"Cannot activate binding: an active binding already exists for "
                            f"workspace '{binding.workspace_id}' and provider "
                            f"'{binding.provider_id}'"
                        )

            self._records[binding.binding_id] = binding
            return binding

    async def delete(self, binding_id: str) -> bool:
        async with self._lock:
            return self._records.pop(binding_id, None) is not None

    @staticmethod
    def _matches(binding: WorkspaceIntegrationBinding, f: WorkspaceBindingFilter) -> bool:
        if f.workspace_id is not None and binding.workspace_id != f.workspace_id:
            return False
        if f.user_id is not None and binding.user_id != f.user_id:
            return False
        if f.provider_id is not None and binding.provider_id != f.provider_id:
            return False
        if f.status is not None and binding.status != f.status:
            return False
        return True
