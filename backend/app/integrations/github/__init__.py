"""GitHub external integration package."""

from app.integrations.github.client import (
    DEFAULT_GITHUB_API_URL,
    DEFAULT_GITHUB_API_VERSION,
    GitHubClient,
)
from app.integrations.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubAuthorizationError,
    GitHubError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseParseError,
    GitHubValidationError,
    translate_github_error,
)
from app.integrations.github.provider import (
    PROVIDER_ID,
    REQUIRED_PERMISSIONS,
    SUPPORTED_CAPABILITIES,
    GitHubProvider,
)
from app.integrations.github.schemas import (
    GitHubIssueSummary,
    GitHubPullRequestSummary,
    GitHubRepoSummary,
    GitHubUserSummary,
    normalize_github_issue,
    normalize_github_pull_request,
    normalize_github_repo,
    normalize_github_user,
)

__all__ = [
    "DEFAULT_GITHUB_API_URL",
    "DEFAULT_GITHUB_API_VERSION",
    "GitHubAPIError",
    "GitHubAuthenticationError",
    "GitHubAuthorizationError",
    "GitHubClient",
    "GitHubError",
    "GitHubIssueSummary",
    "GitHubNetworkError",
    "GitHubNotFoundError",
    "GitHubProvider",
    "GitHubPullRequestSummary",
    "GitHubRateLimitError",
    "GitHubRepoSummary",
    "GitHubResponseParseError",
    "GitHubUserSummary",
    "GitHubValidationError",
    "PROVIDER_ID",
    "REQUIRED_PERMISSIONS",
    "SUPPORTED_CAPABILITIES",
    "normalize_github_issue",
    "normalize_github_pull_request",
    "normalize_github_repo",
    "normalize_github_user",
    "translate_github_error",
]
