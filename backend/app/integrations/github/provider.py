"""Concrete read-only GitHub integration provider."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.integrations.contracts import (
    CredentialReference,
    CredentialResolver,
    IntegrationCapability,
    IntegrationMetadata,
    IntegrationProvider,
    IntegrationRequest,
    IntegrationResponse,
    IntegrationResponseStatus,
    IntegrationStatus,
    PermissionRisk,
    PermissionScope,
    ProviderIdentity,
    ensure_credential_usable,
    validate_provider_request,
)
from app.integrations.github.client import GitHubClient
from app.integrations.github.errors import (
    GitHubError,
    GitHubValidationError,
    translate_github_error,
)
from app.integrations.github.schemas import (
    normalize_github_issue,
    normalize_github_pull_request,
    normalize_github_repo,
    normalize_github_user,
)

PROVIDER_ID = "github"
DISPLAY_NAME = "GitHub"
VERSION = "1.0"

SUPPORTED_CAPABILITIES = (
    IntegrationCapability(
        capability_id="repos.list",
        description="List repositories for the authenticated user or organization.",
    ),
    IntegrationCapability(
        capability_id="repos.get",
        description="Retrieve repository metadata.",
    ),
    IntegrationCapability(
        capability_id="issues.list",
        description="List repository issues.",
    ),
    IntegrationCapability(
        capability_id="issues.get",
        description="Retrieve repository issue by number.",
    ),
    IntegrationCapability(
        capability_id="pulls.list",
        description="List repository pull requests.",
    ),
    IntegrationCapability(
        capability_id="pulls.get",
        description="Retrieve repository pull request by number.",
    ),
    IntegrationCapability(
        capability_id="user.get",
        description="Retrieve authenticated user profile and identity.",
    ),
)

REQUIRED_PERMISSIONS = (
    PermissionScope(
        provider_id=PROVIDER_ID,
        scope_id="repo:read",
        description="Read-only access to repositories, issues, and pull requests.",
        risk=PermissionRisk.low,
    ),
)


class GitHubProvider(IntegrationProvider):
    """Production-ready read-only GitHub provider conforming to IntegrationProvider."""

    def __init__(
        self,
        client: GitHubClient | None = None,
        *,
        credential_resolver: CredentialResolver | None = None,
        token_resolver: Callable[[CredentialReference], Awaitable[str]] | None = None,
        status: IntegrationStatus = IntegrationStatus.available,
        metadata_extra: dict[str, Any] | None = None,
    ) -> None:
        self._client = client or GitHubClient()
        self._credential_resolver = credential_resolver
        self._token_resolver = token_resolver
        self._status = status
        self._metadata = IntegrationMetadata(
            identity=ProviderIdentity(
                provider_id=PROVIDER_ID,
                display_name=DISPLAY_NAME,
                version=VERSION,
            ),
            description="Provider for read-only GitHub workspace and repository integration.",
            status=self._status,
            capabilities=SUPPORTED_CAPABILITIES,
            required_permissions=REQUIRED_PERMISSIONS,
            metadata=metadata_extra or {},
        )

    @property
    def metadata(self) -> IntegrationMetadata:
        """Return stable provider identity and capability metadata."""
        return self._metadata

    def supports_capability(self, capability: str) -> bool:
        """Report whether this provider advertises a capability identifier."""
        return any(item.capability_id == capability for item in self._metadata.capabilities)

    async def execute(self, request: IntegrationRequest) -> IntegrationResponse:
        """Execute one validated read-only operation in the GitHub provider."""
        validate_provider_request(self, request)

        token: str | None = None
        if request.credential is not None:
            ensure_credential_usable(request.credential)
            if self._credential_resolver is not None:
                await self._credential_resolver.resolve(request.credential)
            if self._token_resolver is not None:
                token = await self._token_resolver(request.credential)

        try:
            result, rate_headers = await self._dispatch_operation(request, token)
            response_metadata: dict[str, Any] = {"provider_version": VERSION}
            for header_key in ("x-ratelimit-remaining", "x-ratelimit-limit", "x-ratelimit-reset"):
                if header_key in rate_headers:
                    response_metadata[header_key] = rate_headers[header_key]

            return IntegrationResponse(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                provider_id=request.provider_id,
                capability=request.capability,
                status=IntegrationResponseStatus.succeeded,
                result=result,
                metadata=response_metadata,
            )
        except GitHubError as exc:
            return IntegrationResponse(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                provider_id=request.provider_id,
                capability=request.capability,
                status=IntegrationResponseStatus.failed,
                error=translate_github_error(exc),
            )
        except Exception as exc:
            return IntegrationResponse(
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                provider_id=request.provider_id,
                capability=request.capability,
                status=IntegrationResponseStatus.failed,
                error=translate_github_error(exc),
            )

    async def _dispatch_operation(
        self,
        request: IntegrationRequest,
        token: str | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        params = request.parameters
        cap = request.capability

        if cap == "user.get":
            data, headers = await self._client.get_user(token=token)
            return {"user": normalize_github_user(data)}, headers

        if cap == "repos.list":
            owner = params.get("owner")
            visibility = params.get("visibility")
            per_page = int(params.get("per_page", 30))
            page = int(params.get("page", 1))
            items, headers = await self._client.list_repositories(
                token=token,
                owner=owner,
                visibility=visibility,
                per_page=per_page,
                page=page,
            )
            normalized = [normalize_github_repo(repo) for repo in items]
            return {"repositories": normalized, "count": len(normalized)}, headers

        if cap == "repos.get":
            owner, repo = self._require_owner_and_repo(params)
            data, headers = await self._client.get_repository(owner, repo, token=token)
            return {"repository": normalize_github_repo(data)}, headers

        if cap == "issues.list":
            owner, repo = self._require_owner_and_repo(params)
            state = str(params.get("state", "open"))
            per_page = int(params.get("per_page", 30))
            page = int(params.get("page", 1))
            items, headers = await self._client.list_issues(
                owner,
                repo,
                token=token,
                state=state,
                per_page=per_page,
                page=page,
            )
            normalized = [normalize_github_issue(issue) for issue in items]
            return {"issues": normalized, "count": len(normalized)}, headers

        if cap == "issues.get":
            owner, repo = self._require_owner_and_repo(params)
            issue_number = self._require_number(params, "issue_number")
            data, headers = await self._client.get_issue(
                owner, repo, issue_number, token=token
            )
            return {"issue": normalize_github_issue(data)}, headers

        if cap == "pulls.list":
            owner, repo = self._require_owner_and_repo(params)
            state = str(params.get("state", "open"))
            per_page = int(params.get("per_page", 30))
            page = int(params.get("page", 1))
            items, headers = await self._client.list_pull_requests(
                owner,
                repo,
                token=token,
                state=state,
                per_page=per_page,
                page=page,
            )
            normalized = [normalize_github_pull_request(pr) for pr in items]
            return {"pull_requests": normalized, "count": len(normalized)}, headers

        if cap == "pulls.get":
            owner, repo = self._require_owner_and_repo(params)
            pull_number = self._require_number(params, "pull_number")
            data, headers = await self._client.get_pull_request(
                owner, repo, pull_number, token=token
            )
            return {"pull_request": normalize_github_pull_request(data)}, headers

        raise GitHubError(f"Unsupported GitHub capability: {cap}")

    @staticmethod
    def _require_owner_and_repo(params: dict[str, Any]) -> tuple[str, str]:
        owner = str(params.get("owner", "")).strip()
        repo = str(params.get("repo", "")).strip()
        if not owner or not repo:
            raise GitHubValidationError(
                "Both 'owner' and 'repo' parameters are required for this operation."
            )
        return owner, repo

    @staticmethod
    def _require_number(params: dict[str, Any], field_name: str) -> int:
        val = params.get(field_name) or params.get("number")
        if val is None:
            raise GitHubValidationError(f"Parameter '{field_name}' is required.")
        try:
            return int(val)
        except (ValueError, TypeError) as exc:
            raise GitHubValidationError(f"Parameter '{field_name}' must be an integer.") from exc
