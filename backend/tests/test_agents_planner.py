from __future__ import annotations

import asyncio
import inspect
import uuid

import pytest
from pydantic import ValidationError

from app.domains.agents.context import AgentContextAssembler, ContextBuilder
from app.domains.agents.errors import (
    AgentPlannerLimitError,
    AgentPlannerValidationError,
)
from app.domains.agents.planner import (
    DeterministicPlanner,
    ExecutionPlan,
    PlanMetadata,
    Planner,
    PlanningLimits,
    PlanningRequest,
    PlanStep,
    PlanStepType,
)
from app.domains.agents.schemas import (
    AgentConfiguration,
    ContextAssemblyRequest,
    ExecutionContext,
    UserInformation,
)
from app.domains.agents.tools import (
    ToolDefinition,
    ToolInputContract,
    ToolMetadata,
    ToolOutputContract,
    ToolRegistry,
    ToolState,
)


def make_context(task: str = "Summarize the deployment plan") -> ExecutionContext:
    request = make_context_request(task=task)
    return asyncio.run(AgentContextAssembler().build_context(request))


def make_context_request(task: str = "Summarize the deployment plan") -> ContextAssemblyRequest:
    user_id = uuid.uuid4()
    return (
        ContextBuilder()
        .with_run_id(uuid.uuid4())
        .with_user_id(user_id)
        .with_task(task)
        .with_request_id("planner-request-123")
        .with_runtime_metadata({"source": "planner-test"})
        .with_user_information(
            UserInformation(
                user_id=user_id,
                email="rahul@example.com",
                full_name="Rahul Prakash",
            )
        )
        .with_agent_configuration(
            AgentConfiguration(
                agent_key="assistant",
                agent_type="assistant",
                version="1.0",
                configuration={"mode": "test"},
            )
        )
        .build()
    )


def make_tool(
    tool_id: str = "deployment.lookup",
    *,
    state: ToolState = ToolState.enabled,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        metadata=ToolMetadata(
            display_name="Deployment Lookup",
            description="Describes deployment information without executing an action.",
            version="1.0.0",
            category="knowledge",
            capabilities=("read",),
            state=state,
        ),
        input_contract=ToolInputContract(),
        output_contract=ToolOutputContract(),
    )


def make_request(
    *,
    context: ExecutionContext | None = None,
    task: str | None = None,
    requested_tool_ids: tuple[str, ...] = (),
) -> PlanningRequest:
    context = context or make_context()
    return PlanningRequest(
        task=task or context.task,
        context=context,
        requested_tool_ids=requested_tool_ids,
    )


def test_planning_request_rejects_blank_task_and_context_mismatch() -> None:
    context = make_context()

    with pytest.raises(ValidationError):
        PlanningRequest(task=" ", context=context)

    with pytest.raises(ValidationError, match="must match"):
        PlanningRequest(task="Inspect another task", context=context)

    with pytest.raises(ValidationError, match="duplicates"):
        PlanningRequest(
            task=context.task,
            context=context,
            requested_tool_ids=("deployment.lookup", "deployment.lookup"),
        )


def test_empty_registry_returns_typed_deterministic_instruction_plan() -> None:
    request = make_request()
    planner = DeterministicPlanner(ToolRegistry())

    first = asyncio.run(planner.plan(request))
    second = asyncio.run(planner.plan(request))

    assert isinstance(first, ExecutionPlan)
    assert first == second
    assert first.run_id == request.context.run_id
    assert first.user_id == request.context.user_id
    assert first.metadata.available_tool_ids == ()
    assert first.metadata.requested_tool_ids == ()
    assert [step.order for step in first.steps] == [1]
    assert first.steps[0].step_type == PlanStepType.instruction
    assert first.steps[0].tool_id is None


def test_requested_tools_become_ordered_read_only_plan_steps() -> None:
    registry = ToolRegistry([make_tool("browser.search"), make_tool("deployment.lookup")])
    before = registry.list_tools()
    request = make_request(requested_tool_ids=("deployment.lookup", "browser.search"))

    plan = asyncio.run(DeterministicPlanner(registry).plan(request))

    assert registry.list_tools() == before
    assert [step.step_id for step in plan.steps] == ["step-001", "step-002"]
    assert [step.order for step in plan.steps] == [1, 2]
    assert [step.step_type for step in plan.steps] == [PlanStepType.tool, PlanStepType.tool]
    assert [step.tool_id for step in plan.steps] == ["deployment.lookup", "browser.search"]
    assert plan.steps[0].depends_on == ()
    assert plan.steps[1].depends_on == ("step-001",)
    assert plan.metadata.available_tool_ids == ("browser.search", "deployment.lookup")
    assert plan.metadata.requested_tool_ids == request.requested_tool_ids
    assert not hasattr(plan, "execute")


def test_unknown_or_disabled_requested_tool_is_rejected() -> None:
    registry = ToolRegistry([make_tool("disabled.tool", state=ToolState.disabled)])
    planner = DeterministicPlanner(registry)

    with pytest.raises(AgentPlannerValidationError, match="unavailable tool"):
        asyncio.run(
            planner.plan(make_request(requested_tool_ids=("deployment.lookup",)))
        )

    with pytest.raises(AgentPlannerValidationError, match="unavailable tool"):
        asyncio.run(planner.plan(make_request(requested_tool_ids=("disabled.tool",))))


def test_planner_limits_reject_large_task_context_tools_and_step_output() -> None:
    context = make_context(task="Plan the release safely")

    with pytest.raises(AgentPlannerLimitError, match="task"):
        asyncio.run(
            DeterministicPlanner(limits=PlanningLimits(max_task_length=4)).plan(
                make_request(context=context)
            )
        )

    with pytest.raises(AgentPlannerLimitError, match="context"):
        asyncio.run(
            DeterministicPlanner(limits=PlanningLimits(max_context_bytes=10)).plan(
                make_request(context=context)
            )
        )

    registry = ToolRegistry([make_tool()])
    with pytest.raises(AgentPlannerLimitError, match="too many tools"):
        asyncio.run(
            DeterministicPlanner(
                registry,
                limits=PlanningLimits(max_requested_tools=0),
            ).plan(make_request(context=context, requested_tool_ids=("deployment.lookup",)))
        )

    with pytest.raises(AgentPlannerLimitError, match="description"):
        asyncio.run(
            DeterministicPlanner(limits=PlanningLimits(max_step_description_length=4)).plan(
                make_request(context=context)
            )
        )


def test_plan_models_reject_invalid_content_duplicate_ids_and_bad_ordering() -> None:
    context = make_context()
    metadata = PlanMetadata(context_provider_names=("runtime_metadata",))

    with pytest.raises(ValidationError):
        PlanStep(
            step_id="step-001",
            order=1,
            step_type=PlanStepType.instruction,
            description=" ",
        )

    step = PlanStep(
        step_id="step-001",
        order=1,
        step_type=PlanStepType.instruction,
        description="Use context.",
    )
    duplicate = step.model_copy(update={"order": 2})
    with pytest.raises(ValidationError, match="duplicate step_id"):
        ExecutionPlan(
            plan_id="plan-duplicate",
            run_id=context.run_id,
            user_id=context.user_id,
            task=context.task,
            steps=(step, duplicate),
            metadata=metadata,
        )

    forward_dependency = PlanStep(
        step_id="step-001",
        order=1,
        step_type=PlanStepType.instruction,
        description="Use context.",
        depends_on=("step-002",),
    )
    later = PlanStep(
        step_id="step-002",
        order=2,
        step_type=PlanStepType.instruction,
        description="Continue planning.",
    )
    with pytest.raises(ValidationError, match="earlier steps"):
        ExecutionPlan(
            plan_id="plan-forward",
            run_id=context.run_id,
            user_id=context.user_id,
            task=context.task,
            steps=(forward_dependency, later),
            metadata=metadata,
        )


class InvalidRegistry:
    def list_tools(self) -> tuple[object, ...]:
        return (object(),)


def test_invalid_registry_output_is_rejected() -> None:
    with pytest.raises(AgentPlannerValidationError, match="invalid tool definition"):
        asyncio.run(DeterministicPlanner(InvalidRegistry()).plan(make_request()))


def test_planner_protocol_is_async_and_has_no_executor_or_llm_surface() -> None:
    planner = DeterministicPlanner(ToolRegistry())

    assert isinstance(planner, Planner)
    assert inspect.iscoroutinefunction(planner.plan)
    assert not hasattr(planner, "execute")
    assert not hasattr(planner, "llm")
