class AgentError(Exception):
    """Base class for errors raised by the agent domain."""


class AgentValidationError(AgentError):
    """Raised when an agent domain input violates a validation rule."""


class AgentAuthorizationError(AgentError):
    """Raised when a caller cannot access an agent resource."""


class AgentPolicyDeniedError(AgentAuthorizationError):
    """Raised when an agent operation is denied by policy."""


class AgentNotFoundError(AgentError):
    """Raised when an agent resource cannot be found in the caller's scope."""


class AgentDefinitionNotFoundError(AgentNotFoundError):
    """Raised when an agent definition cannot be found."""


class AgentRunNotFoundError(AgentNotFoundError):
    """Raised when an agent run cannot be found."""


class AgentConflictError(AgentError):
    """Raised when an agent resource conflicts with an existing resource."""


class AgentLifecycleError(AgentValidationError):
    """Raised when an agent run lifecycle transition is invalid."""


class AgentContextError(AgentValidationError):
    """Base error for Context Assembly failures."""


class AgentContextConfigurationError(AgentContextError):
    """Raised when the provider registry cannot satisfy its configuration."""


class AgentContextProviderError(AgentContextError):
    """Raised when a context provider returns invalid or unsafe output."""


class AgentContextLimitError(AgentContextError):
    """Raised when a context request or assembled payload exceeds a limit."""


class AgentMemoryIntegrationError(AgentContextError):
    """Base error for Memory Engine context integration failures."""


class AgentMemoryValidationError(AgentMemoryIntegrationError):
    """Raised when memory retrieval input or output violates a contract."""


class AgentMemoryLimitError(AgentMemoryIntegrationError):
    """Raised when memory context exceeds an integration safety limit."""


class AgentMemoryProviderError(AgentMemoryIntegrationError):
    """Raised when the injected Memory Engine boundary cannot provide context."""


class AgentToolError(AgentValidationError):
    """Base error for Tool Registry failures."""


class AgentToolValidationError(AgentToolError):
    """Raised when a tool contract or registry query is invalid."""


class AgentToolRegistrationError(AgentToolError):
    """Raised when a tool cannot be registered safely."""


class AgentToolLimitError(AgentToolError):
    """Raised when a tool or registry exceeds a configured limit."""


class AgentPlannerError(AgentValidationError):
    """Base error for planner contract and validation failures."""


class AgentPlannerValidationError(AgentPlannerError):
    """Raised when planning input, output, or tool references are invalid."""


class AgentPlannerLimitError(AgentPlannerError):
    """Raised when a planning request or plan exceeds a configured limit."""


class AgentExecutorError(AgentValidationError):
    """Base error for Executor contract and coordination failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "executor_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class AgentExecutorValidationError(AgentExecutorError):
    """Raised when an execution request or plan is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="executor_validation")


class AgentExecutorLimitError(AgentExecutorError):
    """Raised when an execution request exceeds a safety limit."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="executor_limit")


class AgentExecutorPolicyError(AgentExecutorError):
    """Raised when an execution plan violates Executor policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="executor_policy")


class AgentRuntimeError(AgentError):
    """Base error for runtime failures returned by the runtime boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "runtime_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class AgentRuntimeConfigurationError(AgentRuntimeError):
    """Raised when a requested runtime backend is not configured."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="runtime_configuration")


class AgentRuntimeLimitError(AgentRuntimeError):
    """Raised when a runtime safety limit is exceeded."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="runtime_limit")


class AgentTimeoutError(AgentRuntimeError):
    """Raised when a runtime execution exceeds its configured timeout."""

    def __init__(self, message: str = "Runtime execution timed out") -> None:
        super().__init__(message, code="runtime_timeout", retryable=True)


class AgentCancelledError(AgentRuntimeError):
    """Raised when a runtime execution is cancelled."""

    def __init__(self, message: str = "Runtime execution was cancelled") -> None:
        super().__init__(message, code="runtime_cancelled")
