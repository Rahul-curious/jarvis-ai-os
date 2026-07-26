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


class AgentRuntimeError(AgentError):
    """Reserved for runtime failures handled by a future execution adapter."""

