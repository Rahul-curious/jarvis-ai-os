"""HTTP client for GitHub REST API interactions."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.integrations.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubAuthorizationError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseParseError,
)

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITHUB_API_VERSION = "2022-11-28"


class GitHubClient:
    """Async HTTP client for read-only GitHub REST API interactions."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_GITHUB_API_URL,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": DEFAULT_GITHUB_API_VERSION,
            "User-Agent": "JARVIS-AI-OS",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        clean_params = {k: str(v) for k, v in (params or {}).items() if v is not None}

        try:
            if self._client is not None:
                response = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    params=clean_params,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=clean_params,
                    )
        except httpx.RequestError as exc:
            raise GitHubNetworkError(
                f"Network request to GitHub failed: {exc.__class__.__name__}"
            ) from exc

        rate_limit_headers = {
            k.lower(): v
            for k, v in response.headers.items()
            if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"
        }

        if response.status_code >= 400:
            self._handle_error_response(response, rate_limit_headers)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise GitHubResponseParseError(
                f"GitHub response could not be parsed as JSON (status {response.status_code})"
            ) from exc

        return data, rate_limit_headers

    def _handle_error_response(
        self,
        response: httpx.Response,
        rate_headers: dict[str, str],
    ) -> None:
        status_code = response.status_code
        try:
            error_json = response.json()
        except Exception:
            error_json = {}

        message = (
            error_json.get("message")
            if isinstance(error_json, dict)
            else f"GitHub returned HTTP status {status_code}"
        )
        if not message:
            message = f"GitHub returned HTTP status {status_code}"

        if status_code == 401:
            raise GitHubAuthenticationError(message, response_data=error_json)

        if status_code in (403, 429):
            is_rate_limit = (
                rate_headers.get("x-ratelimit-remaining") == "0"
                or status_code == 429
                or "rate limit" in message.lower()
            )
            if is_rate_limit:
                retry_after: int | None = None
                if "retry-after" in rate_headers:
                    try:
                        retry_after = int(rate_headers["retry-after"])
                    except ValueError:
                        pass
                raise GitHubRateLimitError(
                    message,
                    retry_after=retry_after,
                    response_data=error_json,
                )
            raise GitHubAuthorizationError(message, response_data=error_json)

        if status_code == 404:
            raise GitHubNotFoundError(message, response_data=error_json)

        retryable = status_code in {500, 502, 503, 504}
        raise GitHubAPIError(
            message,
            status_code=status_code,
            error_code="github_api_error",
            retryable=retryable,
            response_data=error_json,
        )

    async def get_user(self, *, token: str | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch the authenticated user profile."""
        return await self._request("GET", "/user", token=token)

    async def list_repositories(
        self,
        *,
        token: str | None = None,
        owner: str | None = None,
        visibility: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """List repositories for an owner or for the authenticated user."""
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if visibility:
            params["visibility"] = visibility

        path = f"/users/{owner}/repos" if owner else "/user/repos"
        return await self._request("GET", path, token=token, params=params)

    async def get_repository(
        self,
        owner: str,
        repo: str,
        *,
        token: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch metadata for a specific repository."""
        return await self._request("GET", f"/repos/{owner}/{repo}", token=token)

    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        token: str | None = None,
        state: str = "open",
        per_page: int = 30,
        page: int = 1,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """List issues for a repository."""
        params = {"state": state, "per_page": per_page, "page": page}
        data, headers = await self._request(
            "GET", f"/repos/{owner}/{repo}/issues", token=token, params=params
        )
        # Filter out pull requests since GitHub Issues API includes pull requests by default
        issues = [item for item in data if isinstance(item, dict) and "pull_request" not in item]
        return issues, headers

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        token: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch a specific issue by number."""
        return await self._request(
            "GET", f"/repos/{owner}/{repo}/issues/{issue_number}", token=token
        )

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        token: str | None = None,
        state: str = "open",
        per_page: int = 30,
        page: int = 1,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """List pull requests for a repository."""
        params = {"state": state, "per_page": per_page, "page": page}
        return await self._request(
            "GET", f"/repos/{owner}/{repo}/pulls", token=token, params=params
        )

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        token: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch a specific pull request by number."""
        return await self._request(
            "GET", f"/repos/{owner}/{repo}/pulls/{pull_number}", token=token
        )
