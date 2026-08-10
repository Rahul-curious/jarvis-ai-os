from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.agents.errors import (
    AgentExecutorError,
    AgentExecutorLimitError,
    AgentExecutorPolicyError,
    AgentExecutorValidationError,
)
from app.domains.agents.planner import (
    ExecutionPlan,
    PlanStep,
    PlanStepType,
    ToolRegistryReader,
)
from app.domains.agents.tools import ToolDefinition, ToolState

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_EXECUTOR_NAME = "deterministic"
_EXECUTOR_VERSION = "1.0"


class ExecutionStatus(StrEnum):
    """Lifecycle states owned by the Executor coordination boundary."""

    requested = "requested"
    validating = "validating"
    running = "running"
    waiting_for_approval = "waiting_for_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ExecutionStepStatus(StrEnum):
    """Coordination status for an individual plan step."""

    pending = "pending"
    running = "running"
    completed = "completed"
    deferred = "deferred"
    failed = "failed"
    cancelled = "cancelled"


class ExecutionToolStepMode(StrEnum):
    """How the no-execution boundary handles tool plan steps."""

    defer = "defer"
    reject = "reject"


EXECUTION_STATUS_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.requested: frozenset({ExecutionStatus.validating, ExecutionStatus.cancelled}),
    ExecutionStatus.validating: frozenset(
        {ExecutionStatus.running, ExecutionStatus.failed, ExecutionStatus.cancelled}
    ),
    ExecutionStatus.running: frozenset(
        {
            ExecutionStatus.waiting_for_approval,
            ExecutionStatus.succeeded,
            ExecutionStatus.failed,
            ExecutionStatus.cancelled,
        }
    ),
    ExecutionStatus.waiting_for_approval: frozenset(
        {ExecutionStatus.running, ExecutionStatus.failed, ExecutionStatus.cancelled}
    ),
    ExecutionStatus.succeeded: frozenset(),
    ExecutionStatus.failed: frozenset(),
    ExecutionStatus.cancelled: frozenset(),
}

TERMINAL_EXECUTION_STATUSES = frozenset(
    {ExecutionStatus.succeeded, ExecutionStatus.failed, ExecutionStatus.cancelled}
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionLimits(BaseModel):
    """Explicit bounds for plan progression and emitted execution state."""

    model_config = ConfigDict(frozen=True)

    max_steps: int = Field(default=64, ge=1)
    max_events: int = Field(default=256, ge=1)
    max_metadata_bytes: int = Field(default=64_000, ge=1)
    max_result_bytes: int = Field(default=256_000, ge=1)
    max_step_description_length: int = Field(default=2_000, ge=1)
    max_error_message_length: int = Field(default=2_000, ge=1)


class ExecutionPolicies(BaseModel):
    """Policy gates for coordination; this milestone never enables execution."""

    model_config = ConfigDict(frozen=True)

    allow_instruction_steps: bool = True
    allow_tool_steps: bool = True
    tool_step_mode: ExecutionToolStepMode = ExecutionToolStepMode.defer


class ExecutionRequest(BaseModel):
    """Validated input accepted by an Executor implementation."""

    model_config = ConfigDict(frozen=True)

    plan: ExecutionPlan
    request_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id")
    @classmethod
    def strip_request_id(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def validate_metadata(self) -> ExecutionRequest:
        _ensure_json_mapping(self.metadata, "Execution metadata")
        return self


class ExecutionEvent(BaseModel):
    """Immutable, ordered event emitted by the Executor lifecycle."""

    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1, max_length=120)
    status: ExecutionStatus | None = None
    step_id: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        normalized = value.strip()
        if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
            raise ValueError("execution event_type must be a stable identifier")
        return normalized

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
            raise ValueError("execution event step_id must be a stable identifier")
        return normalized

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @model_validator(mode="after")
    def validate_event_metadata(self) -> ExecutionEvent:
        _ensure_json_mapping(self.metadata, "Execution event metadata")
        return self


class ExecutionStepState(BaseModel):
    """Immutable coordination state for one plan step."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=1)
    status: ExecutionStepStatus = ExecutionStepStatus.pending
    tool_id: str | None = Field(default=None, max_length=120)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2_000)

    @field_validator("step_id", "tool_id")
    @classmethod
    def validate_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
            raise ValueError("execution step identifiers must be stable identifiers")
        return normalized


class ExecutionState(BaseModel):
    """Complete immutable snapshot of one deterministic execution progression."""

    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    run_id: uuid.UUID
    user_id: uuid.UUID
    status: ExecutionStatus
    current_step_id: str | None = None
    step_states: tuple[ExecutionStepState, ...] = Field(default_factory=tuple)
    events: tuple[ExecutionEvent, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_requested: bool = False

    @model_validator(mode="after")
    def validate_state(self) -> ExecutionState:
        _validate_identifier(self.execution_id, "execution_id")
        _validate_identifier(self.plan_id, "plan_id")
        _ensure_json_mapping(self.metadata, "Execution state metadata")
        _validate_event_sequence(self.events)
        return self


class ExecutionResult(BaseModel):
    """Typed result of plan coordination, with no tool or runtime output."""

    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    run_id: uuid.UUID
    user_id: uuid.UUID
    status: ExecutionStatus
    state: ExecutionState
    events: tuple[ExecutionEvent, ...] = Field(default_factory=tuple)
    output_text: str | None = None
    output_metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> ExecutionResult:
        if self.execution_id != self.state.execution_id:
            raise ValueError("execution result identity does not match state")
        if self.plan_id != self.state.plan_id:
            raise ValueError("execution result plan does not match state")
        if self.run_id != self.state.run_id or self.user_id != self.state.user_id:
            raise ValueError("execution result owner does not match state")
        if self.status != self.state.status:
            raise ValueError("execution result status does not match state")
        if self.events != self.state.events:
            raise ValueError("execution result events do not match state")
        _ensure_json_mapping(self.output_metadata, "Execution output metadata")
        if self.error_message is not None and not self.error_message.strip():
            raise ValueError("execution error_message must not be blank")
        return self


class ExecutionValidator:
    """Validates execution requests, plans, state snapshots, and results."""

    def __init__(self, limits: ExecutionLimits | None = None) -> None:
        self.limits = limits or ExecutionLimits()

    def validate_request(self, request: ExecutionRequest) -> None:
        if not isinstance(request, ExecutionRequest):
            raise AgentExecutorValidationError("Execution request is invalid")
        self.validate_plan(request.plan)
        if _json_size(request.metadata, "Execution metadata") > self.limits.max_metadata_bytes:
            raise AgentExecutorLimitError("Execution metadata exceeds the configured size limit")

    def validate_plan(self, plan: ExecutionPlan) -> None:
        if not isinstance(plan, ExecutionPlan):
            raise AgentExecutorValidationError("Executor received an invalid execution plan")
        if not plan.steps:
            raise AgentExecutorValidationError("Execution plan must contain at least one step")
        if len(plan.steps) > self.limits.max_steps:
            raise AgentExecutorLimitError("Execution plan exceeds the configured step limit")

        step_ids = tuple(step.step_id for step in plan.steps)
        orders = tuple(step.order for step in plan.steps)
        if len(step_ids) != len(set(step_ids)):
            raise AgentExecutorValidationError("Execution plan contains duplicate step identifiers")
        if orders != tuple(range(1, len(plan.steps) + 1)):
            raise AgentExecutorValidationError(
                "Execution plan steps must be ordered contiguously from one"
            )
        order_by_id = {step.step_id: step.order for step in plan.steps}
        available_tool_ids = frozenset(plan.metadata.available_tool_ids)
        tool_step_ids: list[str] = []
        for step in plan.steps:
            if len(step.description) > self.limits.max_step_description_length:
                raise AgentExecutorLimitError(
                    "Execution plan step exceeds the configured description limit"
                )
            for dependency in step.depends_on:
                dependency_order = order_by_id.get(dependency)
                if dependency_order is None or dependency_order >= step.order:
                    raise AgentExecutorValidationError(
                        "Execution plan contains an invalid dependency order"
                    )
            if step.step_type == PlanStepType.tool and step.tool_id not in available_tool_ids:
                raise AgentExecutorValidationError(
                    f"Execution plan tool is absent from planner metadata: {step.tool_id}"
                )
            if step.step_type == PlanStepType.tool:
                tool_step_ids.append(step.tool_id)
        if tuple(tool_step_ids) != plan.metadata.requested_tool_ids:
            raise AgentExecutorValidationError(
                "Execution plan tool order does not match planner metadata"
            )

    def validate_state(self, state: ExecutionState, *, plan: ExecutionPlan) -> None:
        if not isinstance(state, ExecutionState):
            raise AgentExecutorValidationError("Executor produced an invalid execution state")
        if state.plan_id != plan.plan_id or state.run_id != plan.run_id:
            raise AgentExecutorValidationError("Execution state identity does not match plan")
        if len(state.events) > self.limits.max_events:
            raise AgentExecutorLimitError("Execution state contains too many events")
        if len(state.step_states) != len(plan.steps):
            raise AgentExecutorValidationError("Execution state does not cover the plan")
        for expected, actual in zip(plan.steps, state.step_states, strict=True):
            if expected.step_id != actual.step_id or expected.order != actual.order:
                raise AgentExecutorValidationError("Execution state step order does not match plan")
            if expected.tool_id != actual.tool_id:
                raise AgentExecutorValidationError(
                    "Execution state tool metadata does not match plan"
                )
        _validate_event_sequence(state.events)

    def validate_result(self, result: ExecutionResult, *, plan: ExecutionPlan) -> None:
        if not isinstance(result, ExecutionResult):
            raise AgentExecutorValidationError("Executor produced an invalid execution result")
        self.validate_state(result.state, plan=plan)
        if result.status != result.state.status:
            raise AgentExecutorValidationError("Execution result status does not match state")
        if result.events != result.state.events:
            raise AgentExecutorValidationError("Execution result events do not match state")
        if len(result.events) > self.limits.max_events:
            raise AgentExecutorLimitError("Execution result contains too many events")
        if (
            _json_size(result.model_dump(mode="json"), "Execution result")
            > self.limits.max_result_bytes
        ):
            raise AgentExecutorLimitError("Execution result exceeds the configured size limit")


@runtime_checkable
class Executor(Protocol):
    """Async contract for deterministic plan coordination."""

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Progress a validated plan without invoking tools or runtimes."""

    async def cancel(self, run_id: uuid.UUID) -> bool:
        """Request cancellation of an active coordination run."""


class _ExecutionLifecycle:
    """Mutable per-run state machine kept private to one Executor invocation."""

    def __init__(
        self,
        *,
        execution_id: str,
        plan: ExecutionPlan,
        request: ExecutionRequest,
        limits: ExecutionLimits,
        clock: Callable[[], datetime],
    ) -> None:
        self.execution_id = execution_id
        self.plan = plan
        self.request = request
        self.limits = limits
        self.clock = clock
        self.status = ExecutionStatus.requested
        self.current_step_id: str | None = None
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.cancellation_requested = False
        self.events: list[ExecutionEvent] = []
        self.step_states = [
            ExecutionStepState(
                step_id=step.step_id,
                order=step.order,
                tool_id=step.tool_id,
            )
            for step in plan.steps
        ]
        self.record(
            event_type="execution.requested",
            status=ExecutionStatus.requested,
            message="Execution coordination requested",
        )

    def transition(
        self,
        target: ExecutionStatus,
        *,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if target not in EXECUTION_STATUS_TRANSITIONS[self.status]:
            raise AgentExecutorValidationError(
                f"Cannot transition execution from {self.status.value} to {target.value}"
            )
        now = self.clock()
        self.status = target
        if target == ExecutionStatus.running and self.started_at is None:
            self.started_at = now
        if target in TERMINAL_EXECUTION_STATUSES:
            self.completed_at = now
        self.record(
            event_type=f"execution.{target.value}",
            status=target,
            message=message,
            metadata=metadata,
            created_at=now,
        )

    def record(
        self,
        *,
        event_type: str,
        status: ExecutionStatus | None = None,
        step_id: str | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if len(self.events) >= self.limits.max_events:
            raise AgentExecutorLimitError("Execution event limit has been reached")
        self.events.append(
            ExecutionEvent(
                sequence=len(self.events),
                event_type=event_type,
                status=status,
                step_id=step_id,
                message=message,
                metadata=dict(metadata or {}),
                created_at=created_at or self.clock(),
            )
        )

    def set_step_status(
        self,
        step: PlanStep,
        status: ExecutionStepStatus,
        *,
        error: AgentExecutorError | None = None,
    ) -> None:
        index = step.order - 1
        current = self.step_states[index]
        now = self.clock()
        started_at = current.started_at or now if status != ExecutionStepStatus.pending else None
        completed_at = (
            now
            if status
            in {
                ExecutionStepStatus.completed,
                ExecutionStepStatus.deferred,
                ExecutionStepStatus.failed,
                ExecutionStepStatus.cancelled,
            }
            else None
        )
        self.step_states[index] = current.model_copy(
            update={
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at,
                "error_code": error.code if error else None,
                "error_message": error.message if error else None,
            }
        )

    def request_cancel(self) -> bool:
        if self.status in TERMINAL_EXECUTION_STATUSES:
            return False
        self.cancellation_requested = True
        return True

    def to_state(self) -> ExecutionState:
        return ExecutionState(
            execution_id=self.execution_id,
            plan_id=self.plan.plan_id,
            run_id=self.plan.run_id,
            user_id=self.plan.user_id,
            status=self.status,
            current_step_id=self.current_step_id,
            step_states=tuple(self.step_states),
            events=tuple(self.events),
            metadata={
                "request_id": self.request.request_id,
                "executor_name": _EXECUTOR_NAME,
                "executor_version": _EXECUTOR_VERSION,
            },
            started_at=self.started_at,
            completed_at=self.completed_at,
            cancellation_requested=self.cancellation_requested,
        )


class DeterministicExecutor:
    """Progresses plans and records outcomes without performing concrete work."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistryReader | None = None,
        policies: ExecutionPolicies | None = None,
        limits: ExecutionLimits | None = None,
        validator: ExecutionValidator | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.tool_registry = tool_registry
        self.policies = policies or ExecutionPolicies()
        self.limits = limits or ExecutionLimits()
        self.validator = validator or ExecutionValidator(self.limits)
        self.clock = clock
        self._active: dict[uuid.UUID, _ExecutionLifecycle] = {}

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.validator.validate_request(request)
        plan = request.plan
        if plan.run_id in self._active:
            raise AgentExecutorValidationError("Execution run is already active")
        self._validate_registry_metadata(plan)

        lifecycle = _ExecutionLifecycle(
            execution_id=_build_execution_id(request),
            plan=plan,
            request=request,
            limits=self.limits,
            clock=self.clock,
        )
        self._active[plan.run_id] = lifecycle
        try:
            lifecycle.transition(
                ExecutionStatus.validating,
                message="Execution request validated",
            )
            self._check_cancelled(lifecycle)
            self._validate_policies(plan)
            lifecycle.transition(
                ExecutionStatus.running,
                message="Execution plan progression started",
            )
            for step in plan.steps:
                await asyncio.sleep(0)
                self._check_cancelled(lifecycle)
                self._progress_step(lifecycle, step)
                await asyncio.sleep(0)
                self._check_cancelled(lifecycle)
            lifecycle.transition(
                ExecutionStatus.succeeded,
                message="Execution plan progression completed",
                metadata={
                    "deferred_tool_steps": sum(
                        state.status == ExecutionStepStatus.deferred
                        for state in lifecycle.step_states
                    ),
                },
            )
            result = self._to_result(lifecycle)
        except AgentExecutorError as exc:
            result = self._failure_result(lifecycle, exc)
        finally:
            self._active.pop(plan.run_id, None)

        self.validator.validate_result(result, plan=plan)
        return result

    async def cancel(self, run_id: uuid.UUID) -> bool:
        lifecycle = self._active.get(run_id)
        return lifecycle.request_cancel() if lifecycle is not None else False

    def _validate_registry_metadata(self, plan: ExecutionPlan) -> None:
        if self.tool_registry is None or not any(
            step.step_type == PlanStepType.tool for step in plan.steps
        ):
            return
        try:
            definitions = self.tool_registry.list_tools()
        except Exception as exc:
            raise AgentExecutorValidationError("Executor could not inspect tool metadata") from exc
        if not isinstance(definitions, tuple):
            definitions = tuple(definitions)
        if any(not isinstance(definition, ToolDefinition) for definition in definitions):
            raise AgentExecutorValidationError("Tool Registry returned invalid metadata")
        available = {
            definition.tool_id
            for definition in definitions
            if definition.metadata.state == ToolState.enabled
        }
        for step in plan.steps:
            if step.step_type == PlanStepType.tool and step.tool_id not in available:
                raise AgentExecutorValidationError(
                    f"Executor tool metadata is unavailable: {step.tool_id}"
                )

    def _validate_policies(self, plan: ExecutionPlan) -> None:
        for step in plan.steps:
            if (
                step.step_type == PlanStepType.instruction
                and not self.policies.allow_instruction_steps
            ):
                raise AgentExecutorPolicyError("Instruction plan steps are denied by policy")
            if step.step_type == PlanStepType.tool:
                if not self.policies.allow_tool_steps:
                    raise AgentExecutorPolicyError("Tool plan steps are denied by policy")
                if self.policies.tool_step_mode == ExecutionToolStepMode.reject:
                    raise AgentExecutorPolicyError(
                        "Tool plan steps are not executable in the Executor boundary"
                    )

    def _progress_step(self, lifecycle: _ExecutionLifecycle, step: PlanStep) -> None:
        lifecycle.current_step_id = step.step_id
        lifecycle.set_step_status(step, ExecutionStepStatus.running)
        lifecycle.record(
            event_type="step.started",
            status=ExecutionStatus.running,
            step_id=step.step_id,
            message="Plan step coordination started",
            metadata={"order": step.order, "step_type": step.step_type.value},
        )
        if step.step_type == PlanStepType.tool:
            status = ExecutionStepStatus.deferred
            event_type = "step.deferred"
            message = "Tool step deferred; concrete tool execution is outside Executor scope"
        else:
            status = ExecutionStepStatus.completed
            event_type = "step.completed"
            message = "Instruction step coordinated; no external work was performed"
        lifecycle.set_step_status(step, status)
        lifecycle.record(
            event_type=event_type,
            status=ExecutionStatus.running,
            step_id=step.step_id,
            message=message,
            metadata={"order": step.order, "step_type": step.step_type.value},
        )
        lifecycle.current_step_id = None

    def _failure_result(
        self,
        lifecycle: _ExecutionLifecycle,
        error: AgentExecutorError,
    ) -> ExecutionResult:
        target = (
            ExecutionStatus.cancelled
            if error.code == "executor_cancelled"
            else ExecutionStatus.failed
        )
        for step in lifecycle.plan.steps:
            state = lifecycle.step_states[step.order - 1]
            if state.status in {ExecutionStepStatus.pending, ExecutionStepStatus.running}:
                lifecycle.set_step_status(
                    step,
                    ExecutionStepStatus.cancelled
                    if target == ExecutionStatus.cancelled
                    else ExecutionStepStatus.failed,
                    error=error,
                )
        if lifecycle.status not in TERMINAL_EXECUTION_STATUSES:
            lifecycle.transition(target, message=error.message)
        return self._to_result(
            lifecycle,
            error_code=error.code,
            error_message=error.message,
            retryable=error.retryable,
        )

    def _to_result(
        self,
        lifecycle: _ExecutionLifecycle,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
    ) -> ExecutionResult:
        state = lifecycle.to_state()
        return ExecutionResult(
            execution_id=state.execution_id,
            plan_id=state.plan_id,
            run_id=state.run_id,
            user_id=state.user_id,
            status=state.status,
            state=state,
            events=state.events,
            output_metadata={
                "coordinated_step_count": len(state.step_states),
                "deferred_tool_step_count": sum(
                    step.status == ExecutionStepStatus.deferred for step in state.step_states
                ),
            },
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
        )

    @staticmethod
    def _check_cancelled(lifecycle: _ExecutionLifecycle) -> None:
        if lifecycle.cancellation_requested:
            raise AgentExecutorError(
                "Execution coordination was cancelled",
                code="executor_cancelled",
            )


def _build_execution_id(request: ExecutionRequest) -> str:
    payload = {
        "plan_id": request.plan.plan_id,
        "run_id": str(request.plan.run_id),
        "user_id": str(request.plan.user_id),
        "request_id": request.request_id,
        "metadata": request.metadata,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"execution-{digest[:32]}"


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a stable identifier")
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _ensure_json_mapping(value: Mapping[str, Any], label: str) -> None:
    if any(not key.strip() for key in value):
        raise ValueError(f"{label} contains a blank key")
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc


def _json_size(value: Any, label: str) -> int:
    try:
        serialized = _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise AgentExecutorValidationError(f"{label} must be JSON serializable") from exc
    return len(serialized.encode("utf-8"))


def _validate_event_sequence(events: tuple[ExecutionEvent, ...]) -> None:
    if tuple(event.sequence for event in events) != tuple(range(len(events))):
        raise ValueError("execution events must have contiguous sequence numbers")
