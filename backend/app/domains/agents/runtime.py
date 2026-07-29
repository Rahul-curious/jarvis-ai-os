from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from app.domains.agents.errors import (
    AgentCancelledError,
    AgentLifecycleError,
    AgentRuntimeError,
    AgentRuntimeLimitError,
    AgentTimeoutError,
    AgentValidationError,
)


class RuntimeStatus(StrEnum):
    """Statuses exposed by the framework-agnostic runtime contract."""

    requested = "requested"
    validating = "validating"
    queued = "queued"
    running = "running"
    waiting_for_approval = "waiting_for_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    retriable = "retriable"


RUNTIME_STATUS_TRANSITIONS: dict[RuntimeStatus, frozenset[RuntimeStatus]] = {
    RuntimeStatus.requested: frozenset(
        {RuntimeStatus.validating, RuntimeStatus.cancelled}
    ),
    RuntimeStatus.validating: frozenset(
        {RuntimeStatus.queued, RuntimeStatus.failed, RuntimeStatus.cancelled}
    ),
    RuntimeStatus.queued: frozenset({RuntimeStatus.running, RuntimeStatus.cancelled}),
    RuntimeStatus.running: frozenset(
        {
            RuntimeStatus.waiting_for_approval,
            RuntimeStatus.succeeded,
            RuntimeStatus.failed,
            RuntimeStatus.cancelled,
            RuntimeStatus.retriable,
        }
    ),
    RuntimeStatus.waiting_for_approval: frozenset(
        {RuntimeStatus.running, RuntimeStatus.failed, RuntimeStatus.cancelled}
    ),
    RuntimeStatus.succeeded: frozenset(),
    RuntimeStatus.failed: frozenset({RuntimeStatus.retriable}),
    RuntimeStatus.cancelled: frozenset(),
    RuntimeStatus.retriable: frozenset({RuntimeStatus.queued, RuntimeStatus.cancelled}),
}

TERMINAL_RUNTIME_STATUSES = frozenset(
    {RuntimeStatus.succeeded, RuntimeStatus.failed, RuntimeStatus.cancelled}
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    """Safety limits and backend selection for a runtime instance."""

    backend: str = "unconfigured"
    timeout_seconds: float = 300.0
    max_task_length: int = 20_000
    max_metadata_keys: int = 100
    max_metadata_bytes: int = 64_000
    max_events: int = 1_000

    def __post_init__(self) -> None:
        if not self.backend.strip():
            raise ValueError("Runtime backend must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("Runtime timeout must be greater than zero")
        if self.max_task_length < 1:
            raise ValueError("Runtime task limit must be greater than zero")
        if self.max_metadata_keys < 1:
            raise ValueError("Runtime metadata key limit must be greater than zero")
        if self.max_metadata_bytes < 1:
            raise ValueError("Runtime metadata byte limit must be greater than zero")
        if self.max_events < 1:
            raise ValueError("Runtime event limit must be greater than zero")


@dataclass(frozen=True, slots=True)
class RuntimeAgentDefinition:
    """Serializable agent-definition input accepted by a runtime."""

    id: uuid.UUID
    agent_key: str
    agent_type: str
    version: str
    configuration: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", dict(self.configuration))


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Execution input that is safe to pass across runtime boundaries."""

    run_id: uuid.UUID
    user_id: uuid.UUID
    task: str
    input_metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    cancellation_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_metadata", dict(self.input_metadata))


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A bounded, structured lifecycle event emitted by a runtime."""

    sequence: int
    event_type: str
    status: RuntimeStatus | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("Runtime event sequence must not be negative")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.status is not None:
            object.__setattr__(self, "status", RuntimeStatus(self.status))


@dataclass(frozen=True, slots=True)
class RuntimeExecution:
    """Output returned by a replaceable execution backend."""

    output_text: str | None = None
    output_metadata: dict[str, Any] = field(default_factory=dict)
    events: tuple[RuntimeEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_metadata", dict(self.output_metadata))
        object.__setattr__(self, "events", tuple(self.events))


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """Stable result returned by every runtime execution attempt."""

    run_id: uuid.UUID
    status: RuntimeStatus
    events: tuple[RuntimeEvent, ...]
    started_at: datetime | None
    completed_at: datetime | None
    output_text: str | None = None
    output_metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RuntimeStatus(self.status))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "output_metadata", dict(self.output_metadata))


class RuntimeExecutor(Protocol):
    """Async execution backend contract implemented by future adapters."""

    async def execute(
        self,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeExecution:
        """Execute a validated request without owning lifecycle persistence."""


RuntimeExecutorCallable = Callable[
    [RuntimeAgentDefinition, RuntimeContext],
    Awaitable[RuntimeExecution],
]


class RuntimeValidator:
    """Validates runtime inputs and backend output metadata at the boundary."""

    def __init__(self, configuration: RuntimeConfiguration) -> None:
        self.configuration = configuration

    def validate_definition(self, definition: RuntimeAgentDefinition) -> None:
        if not isinstance(definition.id, uuid.UUID):
            raise AgentValidationError("Runtime definition id must be a UUID")
        self._require_text(definition.agent_key, "agent_key")
        self._require_text(definition.agent_type, "agent_type")
        self._require_text(definition.version, "version")
        self.validate_metadata(definition.configuration)

    def validate_context(self, context: RuntimeContext) -> None:
        if not isinstance(context.run_id, uuid.UUID):
            raise AgentValidationError("Runtime run_id must be a UUID")
        if not isinstance(context.user_id, uuid.UUID):
            raise AgentValidationError("Runtime user_id must be a UUID")
        if not context.task.strip():
            raise AgentValidationError("Runtime task must not be blank")
        if len(context.task) > self.configuration.max_task_length:
            raise AgentValidationError("Runtime task exceeds the maximum length")
        if context.request_id is not None and len(context.request_id) > 128:
            raise AgentValidationError("Runtime request_id exceeds the maximum length")
        self.validate_metadata(context.input_metadata)

    def validate_execution(self, execution: RuntimeExecution) -> None:
        self.validate_metadata(execution.output_metadata)
        if len(execution.events) > self.configuration.max_events:
            raise AgentRuntimeLimitError("Runtime execution returned too many events")
        for event in execution.events:
            self._require_text(event.event_type, "event_type")
            self.validate_metadata(event.metadata)

    def validate_metadata(self, metadata: Mapping[str, Any]) -> None:
        if len(metadata) > self.configuration.max_metadata_keys:
            raise AgentValidationError("Runtime metadata contains too many keys")
        try:
            serialized = json.dumps(metadata, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise AgentValidationError("Runtime metadata must be JSON serializable") from exc
        if len(serialized.encode("utf-8")) > self.configuration.max_metadata_bytes:
            raise AgentValidationError("Runtime metadata exceeds the maximum size")

    @staticmethod
    def _require_text(value: str, field_name: str) -> None:
        if not value.strip():
            raise AgentValidationError(f"Runtime {field_name} must not be blank")


class RuntimeLifecycle:
    """In-memory state machine used by a single runtime execution."""

    def __init__(
        self,
        *,
        run_id: uuid.UUID,
        max_events: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_events < 1:
            raise ValueError("Runtime event limit must be greater than zero")
        self.run_id = run_id
        self.max_events = max_events
        self._clock = clock
        self._status = RuntimeStatus.requested
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._events: list[RuntimeEvent] = []
        self._cancel_requested = False
        self.record(
            event_type="runtime.requested",
            status=RuntimeStatus.requested,
            message="Runtime execution requested",
        )

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at

    @property
    def events(self) -> tuple[RuntimeEvent, ...]:
        return tuple(self._events)

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def transition(
        self,
        target: RuntimeStatus | str,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        target_status = RuntimeStatus(target)
        if target_status not in RUNTIME_STATUS_TRANSITIONS[self._status]:
            raise AgentLifecycleError(
                f"Cannot transition runtime from {self._status.value} to {target_status.value}"
            )
        if len(self._events) >= self.max_events:
            raise AgentRuntimeLimitError("Runtime event limit has been reached")
        self._status = target_status
        now = self._clock()
        if target_status == RuntimeStatus.running and self._started_at is None:
            self._started_at = now
        if target_status in TERMINAL_RUNTIME_STATUSES:
            self._completed_at = now
        return self.record(
            event_type="runtime.status_changed",
            status=target_status,
            message=message or f"Runtime transitioned to {target_status.value}",
            metadata=metadata,
            created_at=now,
        )

    def record(
        self,
        *,
        event_type: str,
        status: RuntimeStatus | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> RuntimeEvent:
        if len(self._events) >= self.max_events:
            raise AgentRuntimeLimitError("Runtime event limit has been reached")
        event = RuntimeEvent(
            sequence=len(self._events),
            event_type=event_type,
            status=status,
            message=message,
            metadata=dict(metadata or {}),
            created_at=created_at or self._clock(),
        )
        self._events.append(event)
        return event

    def request_cancel(self) -> bool:
        if self._status in TERMINAL_RUNTIME_STATUSES:
            return False
        self._cancel_requested = True
        return True

    def to_result(
        self,
        *,
        output_text: str | None = None,
        output_metadata: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
    ) -> RuntimeResult:
        return RuntimeResult(
            run_id=self.run_id,
            status=self._status,
            events=self.events,
            started_at=self._started_at,
            completed_at=self._completed_at,
            output_text=output_text,
            output_metadata=dict(output_metadata or {}),
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
        )


class AgentRuntime(ABC):
    """Replaceable async runtime interface for agent execution."""

    @abstractmethod
    async def execute(
        self,
        *,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeResult:
        """Execute a definition with validated context and return a structured result."""

    @abstractmethod
    async def cancel(self, run_id: uuid.UUID) -> bool:
        """Request cancellation of an active run; return whether it was active."""


class LifecycleAgentRuntime(AgentRuntime):
    """Lifecycle coordinator around an injected, framework-agnostic executor."""

    def __init__(
        self,
        *,
        configuration: RuntimeConfiguration | None = None,
        executor: RuntimeExecutor | RuntimeExecutorCallable | None = None,
        validator: RuntimeValidator | None = None,
    ) -> None:
        self.configuration = configuration or RuntimeConfiguration()
        self.validator = validator or RuntimeValidator(self.configuration)
        self.executor = executor
        self._active: dict[uuid.UUID, RuntimeLifecycle] = {}
        self._active_contexts: dict[uuid.UUID, RuntimeContext] = {}

    async def execute(
        self,
        *,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeResult:
        self.validator.validate_definition(definition)
        self.validator.validate_context(context)
        if context.run_id in self._active:
            raise AgentRuntimeError(
                "Runtime run is already active",
                code="runtime_already_active",
            )

        lifecycle = RuntimeLifecycle(
            run_id=context.run_id,
            max_events=self.configuration.max_events,
        )
        self._active[context.run_id] = lifecycle
        self._active_contexts[context.run_id] = context
        try:
            lifecycle.transition(RuntimeStatus.validating)
            self._check_cancelled(context, lifecycle)
            lifecycle.transition(RuntimeStatus.queued)
            self._check_cancelled(context, lifecycle)
            lifecycle.transition(RuntimeStatus.running)
            self._check_cancelled(context, lifecycle)

            execution = await self._execute_backend(definition, context)
            self.validator.validate_execution(execution)
            self._check_cancelled(context, lifecycle)
            for event in execution.events:
                lifecycle.record(
                    event_type=event.event_type,
                    status=event.status,
                    message=event.message,
                    metadata=event.metadata,
                    created_at=event.created_at,
                )
            lifecycle.transition(RuntimeStatus.succeeded)
            return lifecycle.to_result(
                output_text=execution.output_text,
                output_metadata=execution.output_metadata,
            )
        except AgentCancelledError as exc:
            return self._failure_result(
                lifecycle,
                status=RuntimeStatus.cancelled,
                error=exc,
            )
        except AgentTimeoutError as exc:
            return self._failure_result(
                lifecycle,
                status=RuntimeStatus.retriable,
                error=exc,
                retryable=True,
            )
        except AgentRuntimeError as exc:
            target = RuntimeStatus.retriable if exc.retryable else RuntimeStatus.failed
            return self._failure_result(
                lifecycle,
                status=target,
                error=exc,
                retryable=exc.retryable,
            )
        finally:
            self._active.pop(context.run_id, None)
            self._active_contexts.pop(context.run_id, None)

    async def cancel(self, run_id: uuid.UUID) -> bool:
        lifecycle = self._active.get(run_id)
        if lifecycle is None:
            return False
        lifecycle.request_cancel()
        context = self._active_contexts.get(run_id)
        if context is not None:
            context.cancellation_event.set()
        return True

    async def _execute_backend(
        self,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeExecution:
        if self.executor is None:
            raise AgentRuntimeError(
                "No runtime execution backend is configured",
                code="runtime_backend_unconfigured",
            )
        try:
            if hasattr(self.executor, "execute"):
                execution = self.executor.execute(definition, context)
            else:
                execution = self.executor(definition, context)
            return await asyncio.wait_for(execution, timeout=self.configuration.timeout_seconds)
        except TimeoutError as exc:
            raise AgentTimeoutError("Runtime execution timed out") from exc
        except asyncio.CancelledError as exc:
            raise AgentCancelledError("Runtime execution was cancelled") from exc
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise AgentRuntimeError(
                "Runtime backend failed",
                code="runtime_backend_error",
            ) from exc

    @staticmethod
    def _check_cancelled(context: RuntimeContext, lifecycle: RuntimeLifecycle) -> None:
        if lifecycle.cancel_requested or context.cancellation_event.is_set():
            raise AgentCancelledError("Runtime execution was cancelled")

    @staticmethod
    def _failure_result(
        lifecycle: RuntimeLifecycle,
        *,
        status: RuntimeStatus,
        error: AgentRuntimeError,
        retryable: bool = False,
    ) -> RuntimeResult:
        if lifecycle.status not in TERMINAL_RUNTIME_STATUSES:
            if status == RuntimeStatus.retriable and lifecycle.status != RuntimeStatus.failed:
                lifecycle.transition(RuntimeStatus.failed, message=error.message)
            if status == RuntimeStatus.retriable:
                lifecycle.transition(RuntimeStatus.retriable, message=error.message)
            else:
                lifecycle.transition(status, message=error.message)
        return lifecycle.to_result(
            error_code=error.code,
            error_message=error.message,
            retryable=retryable,
        )


class UnconfiguredRuntimeExecutor:
    """Explicit default backend until a future runtime adapter is selected."""

    async def execute(
        self,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeExecution:
        del definition, context
        raise AgentRuntimeError(
            "No runtime execution backend is configured",
            code="runtime_backend_unconfigured",
        )


Runtime = AgentRuntime
RuntimeState = RuntimeStatus
RuntimeOutput = RuntimeExecution
