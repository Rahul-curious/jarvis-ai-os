from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domains.agents.context import AgentContextAssembler, ContextBuilder
from app.domains.agents.errors import (
    AgentExecutorLimitError,
    AgentExecutorValidationError,
)
from app.domains.agents.executor import (
    DeterministicExecutor,
    ExecutionLimits,
    ExecutionPolicies,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionStepStatus,
    ExecutionToolStepMode,
    ExecutionValidator,
    Executor,
)
from app.domains.agents.planner import DeterministicPlanner, PlanningRequest
from app.domains.agents.schemas import (
    AgentConfiguration,
    ExecutionContext,
    UserInformation,
)
from app.domains.agents.tools import (
    ToolDefinition,
    ToolInputContract,
    ToolMetadata,
    ToolOutputContract,
    ToolRegistry,
)


def make_context(task: str = "Summarize the deployment plan") -> ExecutionContext:
    user_id = uuid.uuid4()
    request = (
        ContextBuilder()
        .with_run_id(uuid.uuid4())
        .with_user_id(user_id)
        .with_task(task)
        .with_request_id("executor-test")
        .with_runtime_metadata({"source": "executor-test"})
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
                configuration={"mode": "controlled"},
            )
        )
        .build()
    )
    return asyncio.run(AgentContextAssembler().build_context(request))


def make_plan(*, requested_tool_ids: tuple[str, ...] = ()):
    context = make_context()
    request = PlanningRequest(
        task=context.task,
        context=context,
        requested_tool_ids=requested_tool_ids,
    )
    return asyncio.run(DeterministicPlanner(make_registry(requested_tool_ids)).plan(request))


def make_definition(tool_id: str) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        metadata=ToolMetadata(
            display_name="Read-only descriptor",
            description="A descriptor used only for planning metadata.",
            version="1.0.0",
            category="test",
            capabilities=("read",),
        ),
        input_contract=ToolInputContract(),
        output_contract=ToolOutputContract(),
    )


def make_registry(tool_ids: tuple[str, ...]) -> ToolRegistry:
    return ToolRegistry([make_definition(tool_id) for tool_id in tool_ids])


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(microseconds=1)
        return value


def test_execution_request_rejects_invalid_metadata_and_plans() -> None:
    plan = make_plan()

    with pytest.raises(ValidationError):
        ExecutionRequest(plan=plan, metadata={"bad": object()})

    with pytest.raises(AgentExecutorValidationError, match="invalid"):
        asyncio.run(DeterministicExecutor().execute(object()))  # type: ignore[arg-type]


def test_executor_progression_is_typed_observable_and_deterministic() -> None:
    plan = make_plan(requested_tool_ids=("deployment.lookup",))
    request = ExecutionRequest(plan=plan, request_id="stable-request")

    first = asyncio.run(
        DeterministicExecutor(
            tool_registry=make_registry(("deployment.lookup",)),
            clock=FixedClock(),
        ).execute(request)
    )
    second = asyncio.run(
        DeterministicExecutor(
            tool_registry=make_registry(("deployment.lookup",)),
            clock=FixedClock(),
        ).execute(request)
    )

    assert isinstance(first, ExecutionResult)
    assert first == second
    assert first.status == ExecutionStatus.succeeded
    assert [event.sequence for event in first.events] == list(range(len(first.events)))
    assert first.state.current_step_id is None
    assert first.state.step_states[0].status == ExecutionStepStatus.deferred
    assert first.output_metadata["deferred_tool_step_count"] == 1
    assert first.events[-1].event_type == "execution.succeeded"


def test_instruction_steps_are_coordination_only() -> None:
    result = asyncio.run(
        DeterministicExecutor(clock=FixedClock()).execute(ExecutionRequest(plan=make_plan()))
    )

    assert result.status == ExecutionStatus.succeeded
    assert result.state.step_states[0].status == ExecutionStepStatus.completed
    assert result.output_text is None
    assert "external work" in (result.events[-2].message or "")


def test_tool_registry_is_read_only_metadata_only() -> None:
    class ReadOnlyRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def list_tools(self):
            self.calls += 1
            return (make_definition("deployment.lookup"),)

    registry = ReadOnlyRegistry()
    executor = DeterministicExecutor(tool_registry=registry, clock=FixedClock())
    result = asyncio.run(
        executor.execute(
            ExecutionRequest(plan=make_plan(requested_tool_ids=("deployment.lookup",)))
        )
    )

    assert result.status == ExecutionStatus.succeeded
    assert registry.calls == 1
    assert not hasattr(registry, "execute")
    assert not hasattr(executor, "runtime")


def test_policy_rejection_returns_failed_result_and_event() -> None:
    plan = make_plan(requested_tool_ids=("deployment.lookup",))
    executor = DeterministicExecutor(
        policies=ExecutionPolicies(
            allow_tool_steps=True,
            tool_step_mode=ExecutionToolStepMode.reject,
        ),
        clock=FixedClock(),
    )

    result = asyncio.run(executor.execute(ExecutionRequest(plan=plan)))

    assert result.status == ExecutionStatus.failed
    assert result.error_code == "executor_policy"
    assert result.events[-1].event_type == "execution.failed"
    assert isinstance(result.error_message, str)


def test_execution_limits_are_enforced_before_progression() -> None:
    plan = make_plan(requested_tool_ids=("first.tool", "second.tool"))
    executor = DeterministicExecutor(limits=ExecutionLimits(max_steps=1))

    with pytest.raises(AgentExecutorLimitError, match="step limit"):
        asyncio.run(executor.execute(ExecutionRequest(plan=plan)))


def test_executor_rejects_invalid_plan_order_and_dependencies() -> None:
    plan = make_plan()
    invalid = plan.model_copy(update={"steps": (plan.steps[0].model_copy(update={"order": 2}),)})

    with pytest.raises(AgentExecutorValidationError, match="contiguously"):
        ExecutionValidator().validate_plan(invalid)

    invalid_dependency = plan.model_copy(
        update={"steps": (plan.steps[0].model_copy(update={"depends_on": ("step-002",)}),)}
    )
    with pytest.raises(AgentExecutorValidationError, match="dependency"):
        ExecutionValidator().validate_plan(invalid_dependency)


def test_cancellation_is_deterministic_and_does_not_call_runtime() -> None:
    plan = make_plan(requested_tool_ids=("first.tool", "second.tool"))
    executor: DeterministicExecutor
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            asyncio.create_task(executor.cancel(plan.run_id))
        return datetime(2026, 1, 1, tzinfo=UTC)

    executor = DeterministicExecutor(clock=clock)
    result = asyncio.run(executor.execute(ExecutionRequest(plan=plan)))

    assert result.status == ExecutionStatus.cancelled
    assert result.error_code == "executor_cancelled"
    assert result.state.cancellation_requested is True
    assert all(
        step.status in {ExecutionStepStatus.cancelled, ExecutionStepStatus.pending}
        for step in result.state.step_states
    )


def test_validator_rejects_malformed_state_and_result() -> None:
    plan = make_plan()
    result = asyncio.run(
        DeterministicExecutor(clock=FixedClock()).execute(ExecutionRequest(plan=plan))
    )
    malformed_state = result.state.model_copy(update={"events": tuple(reversed(result.events))})

    with pytest.raises((AgentExecutorValidationError, ValueError)):
        ExecutionValidator().validate_state(malformed_state, plan=plan)

    malformed_result = result.model_copy(update={"status": ExecutionStatus.failed})
    with pytest.raises(AgentExecutorValidationError, match="status"):
        ExecutionValidator().validate_result(malformed_result, plan=plan)


def test_executor_protocol_is_async_and_has_no_execution_engine_surface() -> None:
    executor = DeterministicExecutor()

    assert isinstance(executor, Executor)
    assert inspect.iscoroutinefunction(executor.execute)
    assert inspect.iscoroutinefunction(executor.cancel)
    assert not hasattr(executor, "execute_tool")
    assert not hasattr(executor, "invoke_runtime")
    assert not hasattr(executor, "llm")
