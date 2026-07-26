from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.domains.agents.errors import (
    AgentAuthorizationError,
    AgentLifecycleError,
    AgentPolicyDeniedError,
    AgentValidationError,
)
from app.domains.agents.schemas import (
    AgentDefinitionCreateRequest,
    AgentDefinitionStatus,
    AgentDefinitionUpdateRequest,
    AgentRunCreateRequest,
    AgentRunStatus,
    AgentStepCreateRequest,
)

RUN_STATUS_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.requested: frozenset(
        {AgentRunStatus.validating, AgentRunStatus.cancelled}
    ),
    AgentRunStatus.validating: frozenset(
        {AgentRunStatus.queued, AgentRunStatus.failed, AgentRunStatus.cancelled}
    ),
    AgentRunStatus.queued: frozenset({AgentRunStatus.running, AgentRunStatus.cancelled}),
    AgentRunStatus.running: frozenset(
        {
            AgentRunStatus.waiting_for_approval,
            AgentRunStatus.succeeded,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
            AgentRunStatus.retriable,
        }
    ),
    AgentRunStatus.waiting_for_approval: frozenset(
        {AgentRunStatus.running, AgentRunStatus.failed, AgentRunStatus.cancelled}
    ),
    AgentRunStatus.succeeded: frozenset(),
    AgentRunStatus.failed: frozenset({AgentRunStatus.retriable}),
    AgentRunStatus.cancelled: frozenset(),
    AgentRunStatus.retriable: frozenset({AgentRunStatus.queued, AgentRunStatus.cancelled}),
}


@dataclass(frozen=True)
class AgentLimits:
    max_task_length: int = 20_000
    max_metadata_keys: int = 100
    max_metadata_bytes: int = 64_000
    max_steps_per_run: int = 100
    max_events_per_run: int = 1_000
    max_artifact_size_bytes: int = 100 * 1024 * 1024


class AgentPolicy:
    """Centralized validation, ownership, lifecycle, and resource-limit policy."""

    def __init__(self, limits: AgentLimits | None = None) -> None:
        self.limits = limits or AgentLimits()

    def ensure_owner(
        self,
        *,
        resource_user_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> None:
        if resource_user_id != current_user_id:
            raise AgentAuthorizationError("Agent resource is not available")

    def ensure_definition_usable(self, status: AgentDefinitionStatus | str) -> None:
        normalized_status = AgentDefinitionStatus(status)
        if normalized_status != AgentDefinitionStatus.active:
            raise AgentPolicyDeniedError("Agent definition is not active")

    def validate_definition_create(self, payload: AgentDefinitionCreateRequest) -> None:
        self._validate_metadata(payload.configuration)

    def validate_definition_update(self, payload: AgentDefinitionUpdateRequest) -> None:
        if payload.configuration is not None:
            self._validate_metadata(payload.configuration)
        if payload.status == AgentDefinitionStatus.archived:
            return

    def validate_run_create(self, payload: AgentRunCreateRequest) -> None:
        if len(payload.task) > self.limits.max_task_length:
            raise AgentValidationError("Agent task exceeds the maximum length")
        self._validate_metadata(payload.input_metadata)

    def validate_step_create(self, payload: AgentStepCreateRequest) -> None:
        self._validate_metadata(payload.input_metadata)
        self._validate_metadata(payload.output_metadata)

    def validate_event_metadata(self, metadata: dict[str, Any]) -> None:
        self._validate_metadata(metadata)

    def validate_artifact_size(self, size_bytes: int) -> None:
        if size_bytes > self.limits.max_artifact_size_bytes:
            raise AgentValidationError("Agent artifact exceeds the maximum size")

    def validate_status_transition(
        self,
        *,
        current_status: AgentRunStatus | str,
        target_status: AgentRunStatus | str,
    ) -> None:
        current = AgentRunStatus(current_status)
        target = AgentRunStatus(target_status)
        if target not in RUN_STATUS_TRANSITIONS[current]:
            raise AgentLifecycleError(
                f"Cannot transition agent run from {current.value} to {target.value}"
            )

    def validate_step_count(self, count: int) -> None:
        if count >= self.limits.max_steps_per_run:
            raise AgentPolicyDeniedError("Agent run has reached the maximum step count")

    def validate_event_count(self, count: int) -> None:
        if count >= self.limits.max_events_per_run:
            raise AgentPolicyDeniedError("Agent run has reached the maximum event count")

    def _validate_metadata(self, metadata: dict[str, Any]) -> None:
        if len(metadata) > self.limits.max_metadata_keys:
            raise AgentValidationError("Agent metadata contains too many keys")
        try:
            serialized = json.dumps(metadata, separators=(",", ":"), default=str)
        except (TypeError, ValueError) as exc:
            raise AgentValidationError("Agent metadata must be JSON serializable") from exc
        if len(serialized.encode("utf-8")) > self.limits.max_metadata_bytes:
            raise AgentValidationError("Agent metadata exceeds the maximum size")
