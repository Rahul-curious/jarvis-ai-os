from __future__ import annotations

from typing import TYPE_CHECKING

from app.domains.agents.errors import AgentRuntimeConfigurationError
from app.domains.agents.runtime import (
    AgentRuntime,
    LifecycleAgentRuntime,
    RuntimeConfiguration,
    RuntimeExecutor,
    RuntimeExecutorCallable,
    UnconfiguredRuntimeExecutor,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class AgentRuntimeFactory:
    """Constructs runtime implementations without exposing backend details to callers."""

    @classmethod
    def create(
        cls,
        *,
        configuration: RuntimeConfiguration | None = None,
        executor: RuntimeExecutor | RuntimeExecutorCallable | None = None,
    ) -> AgentRuntime:
        runtime_configuration = configuration or RuntimeConfiguration()
        if executor is None and runtime_configuration.backend != "unconfigured":
            raise AgentRuntimeConfigurationError(
                f"Unsupported runtime backend: {runtime_configuration.backend}"
            )
        return LifecycleAgentRuntime(
            configuration=runtime_configuration,
            executor=executor or UnconfiguredRuntimeExecutor(),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentRuntime:
        return cls.create(
            configuration=RuntimeConfiguration(
                backend=settings.agent_runtime_backend,
                timeout_seconds=settings.agent_runtime_timeout_seconds,
                max_task_length=settings.agent_runtime_max_task_length,
                max_metadata_keys=settings.agent_runtime_max_metadata_keys,
                max_metadata_bytes=settings.agent_runtime_max_metadata_bytes,
                max_events=settings.agent_runtime_max_events,
            )
        )


RuntimeFactory = AgentRuntimeFactory
