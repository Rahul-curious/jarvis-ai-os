"""GitHub-specific errors and provider-neutral error translation.

This module ensures that external HTTP errors and status codes are mapped into safe,
structured IntegrationErrorInfo objects without leaking secrets or transport details.
"""

from __future__ import annotations

from typing import Any

from app.integrations.contracts import IntegrationErrorInfo
from app.integrations.errors import IntegrationError


class GitHubError(IntegrationError):
    """Base exception for all GitHub-specific integration failures."""


class GitHubAPIError(GitHubError):
    """Raised when GitHub returns an error HTTP status or unexpected payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        error_code: str = "github_api_error",
        retryable: bool = False,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.response_data = response_data or {}


class GitHubAuthenticationError(GitHubAPIError):
    """Raised on HTTP 401 or bad credentials."""

    def __init__(
        self,
        message: str = "GitHub authentication failed or credentials are invalid.",
        *,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=401,
            error_code="authentication_failed",
            retryable=False,
            response_data=response_data,
        )


class GitHubAuthorizationError(GitHubAPIError):
    """Raised on HTTP 403 when access is forbidden."""

    def __init__(
        self,
        message: str = "Access to the requested GitHub resource was forbidden.",
        *,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=403,
            error_code="forbidden",
            retryable=False,
            response_data=response_data,
        )


class GitHubNotFoundError(GitHubAPIError):
    """Raised on HTTP 404 when repository, issue, or resource is not found."""

    def __init__(
        self,
        message: str = "Requested GitHub resource was not found.",
        *,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=404,
            error_code="resource_not_found",
            retryable=False,
            response_data=response_data,
        )


class GitHubRateLimitError(GitHubAPIError):
    """Raised on HTTP 403 or 429 when GitHub API rate limits are exceeded."""

    def __init__(
        self,
        message: str = "GitHub API rate limit exceeded.",
        *,
        retry_after: int | None = None,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=429,
            error_code="rate_limit_exceeded",
            retryable=True,
            response_data=response_data,
        )
        self.retry_after = retry_after


class GitHubNetworkError(GitHubError):
    """Raised on network timeout or connection failure."""

    def __init__(self, message: str = "Network connection to GitHub failed.") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = 503
        self.error_code = "network_failure"
        self.retryable = True


class GitHubResponseParseError(GitHubError):
    """Raised when GitHub returns a malformed or non-JSON response."""

    def __init__(self, message: str = "Failed to parse GitHub response payload.") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = 502
        self.error_code = "malformed_response"
        self.retryable = False


class GitHubValidationError(GitHubError):
    """Raised when required operation parameters are missing or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = "invalid_parameters"
        self.retryable = False


def translate_github_error(exc: Exception) -> IntegrationErrorInfo:
    """Translate an internal or external error into a safe IntegrationErrorInfo.

    Ensures no authorization headers, tokens, or raw secrets are present in the output.
    """
    if isinstance(exc, GitHubValidationError):
        return IntegrationErrorInfo(
            code=exc.error_code,
            message=exc.message[:2000],
            retryable=False,
            metadata={},
        )

    if isinstance(exc, GitHubAPIError):
        metadata: dict[str, Any] = {"status_code": exc.status_code}
        if isinstance(exc, GitHubRateLimitError) and exc.retry_after is not None:
            metadata["retry_after"] = exc.retry_after

        return IntegrationErrorInfo(
            code=exc.error_code,
            message=exc.message[:2000],
            retryable=exc.retryable,
            metadata=metadata,
        )

    if isinstance(exc, GitHubNetworkError):
        return IntegrationErrorInfo(
            code=exc.error_code,
            message=exc.message[:2000],
            retryable=exc.retryable,
            metadata={"status_code": exc.status_code},
        )

    if isinstance(exc, GitHubResponseParseError):
        return IntegrationErrorInfo(
            code=exc.error_code,
            message=exc.message[:2000],
            retryable=exc.retryable,
            metadata={"status_code": exc.status_code},
        )

    if isinstance(exc, GitHubError):
        return IntegrationErrorInfo(
            code="github_error",
            message=str(exc)[:2000],
            retryable=False,
            metadata={},
        )

    # General unexpected exception fallback
    return IntegrationErrorInfo(
        code="internal_provider_error",
        message="An unexpected error occurred during GitHub provider execution.",
        retryable=False,
        metadata={},
    )
