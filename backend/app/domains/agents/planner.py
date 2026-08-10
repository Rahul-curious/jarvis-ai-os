from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.agents.errors import (
    AgentPlannerLimitError,
    AgentPlannerValidationError,
)
from app.domains.agents.schemas import ExecutionContext
from app.domains.agents.tools import ToolDefinition, ToolRegistry

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
_PLANNER_NAME = "deterministic"
_PLANNER_VERSION = "1.0"


class PlanStepType(StrEnum):
    """Planner step categories. They describe intent but do not execute work."""

    instruction = "instruction"
    tool = "tool"


class PlanningLimits(BaseModel):
    """Explicit boundaries for deterministic planning."""

    model_config = ConfigDict(frozen=True)

    max_task_length: int = Field(default=20_000, ge=1)
    max_context_bytes: int = Field(default=256_000, ge=1)
    max_metadata_bytes: int = Field(default=64_000, ge=1)
    max_requested_tools: int = Field(default=32, ge=0)
    max_plan_steps: int = Field(default=64, ge=1)
    max_step_description_length: int = Field(default=2_000, ge=1)


class PlanningRequest(BaseModel):
    """Framework-neutral input accepted by a planner."""

    model_config = ConfigDict(frozen=True)

    task: str = Field(min_length=1, max_length=20_000)
    context: ExecutionContext
    requested_tool_ids: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        return _strip_required(value, "task")

    @field_validator("requested_tool_ids")
    @classmethod
    def normalize_requested_tool_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_identifiers(value, "requested_tool_ids")

    @model_validator(mode="after")
    def validate_context_compatibility(self) -> PlanningRequest:
        if self.task != self.context.task:
            raise ValueError("planning task must match the validated execution context task")
        _ensure_json_mapping(self.metadata, "planning metadata")
        return self


class PlanMetadata(BaseModel):
    """Deterministic metadata describing planner inputs and discovery state."""

    model_config = ConfigDict(frozen=True)

    planner_name: str = Field(default=_PLANNER_NAME, min_length=1, max_length=80)
    planner_version: str = Field(default=_PLANNER_VERSION, min_length=1, max_length=32)
    context_provider_names: tuple[str, ...] = Field(default_factory=tuple)
    available_tool_ids: tuple[str, ...] = Field(default_factory=tuple)
    requested_tool_ids: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("planner_name", "planner_version")
    @classmethod
    def strip_metadata_text(cls, value: str) -> str:
        return _strip_required(value, "plan metadata value")

    @field_validator("context_provider_names", "available_tool_ids", "requested_tool_ids")
    @classmethod
    def normalize_identifier_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_identifiers(value, "plan metadata identifiers")


class PlanStep(BaseModel):
    """One ordered unit of planned future work."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=1)
    step_type: PlanStepType
    description: str = Field(min_length=1, max_length=2_000)
    tool_id: str | None = Field(default=None, max_length=120)
    depends_on: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, value: str) -> str:
        return _validate_identifier(value, "step_id")

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return _strip_required(value, "step description")

    @field_validator("tool_id")
    @classmethod
    def validate_tool_id(cls, value: str | None) -> str | None:
        return _validate_identifier(value, "tool_id") if value is not None else None

    @field_validator("depends_on")
    @classmethod
    def normalize_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_identifiers(value, "depends_on")

    @model_validator(mode="after")
    def validate_tool_step(self) -> PlanStep:
        if self.step_type == PlanStepType.tool and self.tool_id is None:
            raise ValueError("tool plan steps must reference a tool_id")
        if self.step_type == PlanStepType.instruction and self.tool_id is not None:
            raise ValueError("instruction plan steps must not reference a tool_id")
        if self.step_id in self.depends_on:
            raise ValueError("plan steps must not depend on themselves")
        return self


class ExecutionPlan(BaseModel):
    """Validated, deterministic plan returned before any runtime execution."""

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(min_length=1, max_length=120)
    run_id: uuid.UUID
    user_id: uuid.UUID
    task: str = Field(min_length=1, max_length=20_000)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=64)
    metadata: PlanMetadata

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, value: str) -> str:
        return _validate_identifier(value, "plan_id")

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        return _strip_required(value, "task")

    @model_validator(mode="after")
    def validate_steps(self) -> ExecutionPlan:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("execution plan steps must not contain duplicate step_id values")

        orders = [step.order for step in self.steps]
        if len(orders) != len(set(orders)):
            raise ValueError("execution plan steps must not contain duplicate order values")
        if sorted(orders) != list(range(1, len(self.steps) + 1)):
            raise ValueError("execution plan steps must be ordered contiguously from 1")

        order_by_id = {step.step_id: step.order for step in self.steps}
        for step in self.steps:
            for dependency in step.depends_on:
                dependency_order = order_by_id.get(dependency)
                if dependency_order is None:
                    raise ValueError("execution plan dependency references an unknown step")
                if dependency_order >= step.order:
                    raise ValueError("execution plan dependencies must reference earlier steps")
        return self


class PlanningValidator:
    """Boundary validator for planner input, output, and limit enforcement."""

    def __init__(self, limits: PlanningLimits | None = None) -> None:
        self.limits = limits or PlanningLimits()

    def validate_request(self, request: PlanningRequest) -> None:
        if not isinstance(request, PlanningRequest):
            raise AgentPlannerValidationError("Planning request is invalid")
        if len(request.task) > self.limits.max_task_length:
            raise AgentPlannerLimitError("Planning task exceeds the configured length limit")
        if request.task != request.context.task:
            raise AgentPlannerValidationError(
                "Planning task must match the validated execution context task"
            )
        if len(request.requested_tool_ids) > self.limits.max_requested_tools:
            raise AgentPlannerLimitError("Planning request references too many tools")

        metadata_size = _json_size(request.metadata, "Planning metadata")
        if metadata_size > self.limits.max_metadata_bytes:
            raise AgentPlannerLimitError("Planning metadata exceeds the configured size limit")

        context_size = _json_size(
            request.context.model_dump(mode="json"),
            "Execution context",
        )
        if context_size > self.limits.max_context_bytes:
            raise AgentPlannerLimitError("Execution context exceeds the planner size limit")

    def validate_plan_for_request(
        self,
        plan: ExecutionPlan,
        request: PlanningRequest,
        *,
        available_tool_ids: frozenset[str],
    ) -> None:
        if not isinstance(plan, ExecutionPlan):
            raise AgentPlannerValidationError("Planner returned an invalid execution plan")
        if plan.run_id != request.context.run_id or plan.user_id != request.context.user_id:
            raise AgentPlannerValidationError("Execution plan identity does not match context")
        if plan.task != request.task:
            raise AgentPlannerValidationError("Execution plan task does not match request")
        if plan.metadata.requested_tool_ids != request.requested_tool_ids:
            raise AgentPlannerValidationError("Execution plan metadata changed requested tools")
        if len(plan.steps) > self.limits.max_plan_steps:
            raise AgentPlannerLimitError("Execution plan exceeds the configured step limit")

        tool_step_ids: list[str] = []
        for step in plan.steps:
            if len(step.description) > self.limits.max_step_description_length:
                raise AgentPlannerLimitError(
                    "Execution plan step exceeds the configured description limit"
                )
            if step.step_type == PlanStepType.tool:
                if step.tool_id not in available_tool_ids:
                    raise AgentPlannerValidationError(
                        f"Execution plan references an unavailable tool: {step.tool_id}"
                    )
                tool_step_ids.append(step.tool_id)

        if tuple(tool_step_ids) != request.requested_tool_ids:
            raise AgentPlannerValidationError("Execution plan changed requested tool order")


class ToolRegistryReader(Protocol):
    """Read-only tool discovery surface used by the planner."""

    def list_tools(
        self,
        *,
        category: str | None = None,
        capability: str | None = None,
        include_disabled: bool = False,
    ) -> tuple[ToolDefinition, ...]:
        """Return available tool contracts without exposing execution."""


@runtime_checkable
class Planner(Protocol):
    """Async planner contract consumed by future orchestration layers."""

    async def plan(self, request: PlanningRequest) -> ExecutionPlan:
        """Return a validated execution plan without executing it."""


class DeterministicPlanner:
    """Small deterministic planner for Phase 6.5 contract validation."""

    def __init__(
        self,
        tool_registry: ToolRegistryReader | None = None,
        *,
        limits: PlanningLimits | None = None,
        validator: PlanningValidator | None = None,
    ) -> None:
        self.tool_registry = tool_registry or ToolRegistry()
        self.validator = validator or PlanningValidator(limits)

    async def plan(self, request: PlanningRequest) -> ExecutionPlan:
        self.validator.validate_request(request)
        available_tools = self._discover_tools()
        available_by_id = {tool.tool_id: tool for tool in available_tools}
        requested_tools = self._resolve_requested_tools(request, available_by_id)
        steps = self._build_steps(request, requested_tools)
        plan = ExecutionPlan(
            plan_id=self._build_plan_id(request, available_tools),
            run_id=request.context.run_id,
            user_id=request.context.user_id,
            task=request.task,
            steps=steps,
            metadata=PlanMetadata(
                context_provider_names=tuple(
                    section.provider for section in request.context.sections
                ),
                available_tool_ids=tuple(tool.tool_id for tool in available_tools),
                requested_tool_ids=request.requested_tool_ids,
            ),
        )
        self.validator.validate_plan_for_request(
            plan,
            request,
            available_tool_ids=frozenset(available_by_id),
        )
        return plan

    async def create_plan(self, request: PlanningRequest) -> ExecutionPlan:
        """Compatibility alias for callers that prefer command-style naming."""

        return await self.plan(request)

    def _discover_tools(self) -> tuple[ToolDefinition, ...]:
        try:
            tools = self.tool_registry.list_tools()
        except Exception as exc:
            raise AgentPlannerValidationError("Planner could not discover tools") from exc
        if not isinstance(tools, tuple):
            tools = tuple(tools)
        for tool in tools:
            if not isinstance(tool, ToolDefinition):
                raise AgentPlannerValidationError(
                    "Tool registry returned an invalid tool definition"
                )
        return tuple(sorted(tools, key=lambda tool: tool.tool_id))

    def _resolve_requested_tools(
        self,
        request: PlanningRequest,
        available_by_id: Mapping[str, ToolDefinition],
    ) -> tuple[ToolDefinition, ...]:
        resolved: list[ToolDefinition] = []
        for tool_id in request.requested_tool_ids:
            tool = available_by_id.get(tool_id)
            if tool is None:
                raise AgentPlannerValidationError(
                    f"Planning request references an unavailable tool: {tool_id}"
                )
            resolved.append(tool)
        return tuple(resolved)

    def _build_steps(
        self,
        request: PlanningRequest,
        requested_tools: Iterable[ToolDefinition],
    ) -> tuple[PlanStep, ...]:
        del request
        tools = tuple(requested_tools)
        if not tools:
            return (
                PlanStep(
                    step_id="step-001",
                    order=1,
                    step_type=PlanStepType.instruction,
                    description="Use the validated execution context to address the task.",
                ),
            )

        steps: list[PlanStep] = []
        for index, tool in enumerate(tools, start=1):
            step_id = f"step-{index:03d}"
            steps.append(
                PlanStep(
                    step_id=step_id,
                    order=index,
                    step_type=PlanStepType.tool,
                    description=(
                        f"Use registered tool contract {tool.tool_id!r} "
                        "as a planned future action."
                    ),
                    tool_id=tool.tool_id,
                    depends_on=() if index == 1 else (f"step-{index - 1:03d}",),
                )
            )
        return tuple(steps)

    def _build_plan_id(
        self,
        request: PlanningRequest,
        available_tools: tuple[ToolDefinition, ...],
    ) -> str:
        payload = {
            "planner_name": _PLANNER_NAME,
            "planner_version": _PLANNER_VERSION,
            "task": request.task,
            "run_id": str(request.context.run_id),
            "user_id": str(request.context.user_id),
            "context": request.context.model_dump(mode="json"),
            "requested_tool_ids": request.requested_tool_ids,
            "available_tool_ids": tuple(tool.tool_id for tool in available_tools),
            "metadata": request.metadata,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return f"plan-{digest[:32]}"


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = _strip_required(value, field_name)
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a stable identifier")
    return normalized


def _normalize_identifiers(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_validate_identifier(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must not contain duplicates")
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
        raise AgentPlannerValidationError(f"{label} must be JSON serializable") from exc
    return len(serialized.encode("utf-8"))
