from __future__ import annotations

import asyncio
import uuid

import pytest

from app.api.dependencies import get_agent_runtime
from app.core.config import Settings
from app.domains.agents.errors import (
    AgentLifecycleError,
    AgentRuntimeConfigurationError,
    AgentRuntimeError,
    AgentValidationError,
)
from app.domains.agents.factory import AgentRuntimeFactory
from app.domains.agents.runtime import (
    LifecycleAgentRuntime,
    RuntimeAgentDefinition,
    RuntimeConfiguration,
    RuntimeContext,
    RuntimeExecution,
    RuntimeLifecycle,
    RuntimeStatus,
)


def make_definition() -> RuntimeAgentDefinition:
    return RuntimeAgentDefinition(
        id=uuid.uuid4(),
        agent_key="assistant",
        agent_type="assistant",
        version="1.0",
        configuration={"mode": "test"},
    )


def make_context(*, task: str = "Inspect the deployment plan") -> RuntimeContext:
    return RuntimeContext(
        run_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        task=task,
        input_metadata={"source": "test"},
    )


def test_lifecycle_enforces_transitions_and_records_ordered_events() -> None:
    lifecycle = RuntimeLifecycle(run_id=uuid.uuid4(), max_events=20)

    lifecycle.transition(RuntimeStatus.validating)
    lifecycle.transition(RuntimeStatus.queued)
    lifecycle.transition(RuntimeStatus.running)
    lifecycle.transition(RuntimeStatus.succeeded)

    assert lifecycle.status == RuntimeStatus.succeeded
    assert [event.sequence for event in lifecycle.events] == list(range(5))
    assert lifecycle.started_at is not None
    assert lifecycle.completed_at is not None

    with pytest.raises(AgentLifecycleError):
        lifecycle.transition(RuntimeStatus.running)


def test_runtime_validates_context_before_execution() -> None:
    runtime = LifecycleAgentRuntime(
        configuration=RuntimeConfiguration(max_task_length=10),
        executor=lambda _definition, _context: _completed_execution(),
    )

    with pytest.raises(AgentValidationError):
        asyncio.run(
            runtime.execute(
                definition=make_definition(),
                context=make_context(task="this task is too long"),
            )
        )


async def _completed_execution() -> RuntimeExecution:
    return RuntimeExecution(output_text="completed")


def test_runtime_returns_structured_success_result_from_async_executor() -> None:
    async def executor(_definition, _context) -> RuntimeExecution:
        return RuntimeExecution(output_text="completed", output_metadata={"source": "test"})

    runtime = LifecycleAgentRuntime(executor=executor)
    result = asyncio.run(runtime.execute(definition=make_definition(), context=make_context()))

    assert result.status == RuntimeStatus.succeeded
    assert result.output_text == "completed"
    assert result.output_metadata == {"source": "test"}
    assert result.error_code is None
    assert result.events[-1].status == RuntimeStatus.succeeded


def test_runtime_converts_backend_errors_to_failed_results() -> None:
    async def executor(_definition, _context) -> RuntimeExecution:
        raise AgentRuntimeError("backend unavailable", code="backend_unavailable")

    runtime = LifecycleAgentRuntime(executor=executor)
    result = asyncio.run(runtime.execute(definition=make_definition(), context=make_context()))

    assert result.status == RuntimeStatus.failed
    assert result.error_code == "backend_unavailable"
    assert result.error_message == "backend unavailable"


def test_runtime_converts_timeout_to_retriable_result() -> None:
    async def executor(_definition, _context) -> RuntimeExecution:
        await asyncio.Event().wait()
        return RuntimeExecution(output_text="unreachable")

    runtime = LifecycleAgentRuntime(
        configuration=RuntimeConfiguration(timeout_seconds=0.001),
        executor=executor,
    )
    result = asyncio.run(runtime.execute(definition=make_definition(), context=make_context()))

    assert result.status == RuntimeStatus.retriable
    assert result.error_code == "runtime_timeout"
    assert result.retryable is True


def test_runtime_cancel_requests_stop_and_returns_cancelled_result() -> None:
    async def scenario() -> RuntimeStatus:
        async def executor(_definition, context) -> RuntimeExecution:
            await context.cancellation_event.wait()
            return RuntimeExecution(output_text="cancelled")

        runtime = LifecycleAgentRuntime(executor=executor)
        task = asyncio.create_task(
            runtime.execute(definition=make_definition(), context=context)
        )
        await asyncio.sleep(0)
        assert await runtime.cancel(context.run_id) is True
        result = await task
        return result.status

    context = make_context()
    assert asyncio.run(scenario()) == RuntimeStatus.cancelled


def test_default_factory_is_explicitly_unconfigured() -> None:
    runtime = AgentRuntimeFactory.create()
    result = asyncio.run(runtime.execute(definition=make_definition(), context=make_context()))

    assert result.status == RuntimeStatus.failed
    assert result.error_code == "runtime_backend_unconfigured"


def test_factory_maps_settings_into_runtime_configuration() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-for-runtime-suite-32-chars",
        agent_runtime_timeout_seconds=2,
        agent_runtime_max_events=12,
    )
    runtime = get_agent_runtime(settings)

    assert isinstance(runtime, LifecycleAgentRuntime)
    assert runtime.configuration.timeout_seconds == 2
    assert runtime.configuration.max_events == 12


def test_runtime_rejects_unsupported_factory_backend() -> None:
    with pytest.raises(AgentRuntimeConfigurationError, match="Unsupported runtime backend"):
        AgentRuntimeFactory.create(configuration=RuntimeConfiguration(backend="langgraph"))
