"""Errors raised while validating integration contracts."""


class IntegrationError(Exception):
    """Base error for the provider-neutral integration boundary."""


class IntegrationValidationError(IntegrationError):
    """Raised when an integration contract is malformed or incomplete."""


class IntegrationConfigurationError(IntegrationValidationError):
    """Raised when provider metadata cannot describe a valid integration."""


class IntegrationCapabilityError(IntegrationValidationError):
    """Raised when a request references an unsupported capability."""


class IntegrationPermissionError(IntegrationValidationError):
    """Raised when required permission declarations are missing from a request."""


class IntegrationCredentialError(IntegrationValidationError):
    """Raised when a credential reference violates the secret-handling contract."""


class IntegrationProviderUnavailableError(IntegrationError):
    """Raised when a provider cannot accept operations in its current state."""
