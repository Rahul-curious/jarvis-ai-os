"""Comprehensive test suite for Phase 7.4 GitHub Provider (Issue #13)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.integrations import (
    CredentialOwnership,
    CredentialReference,
    CredentialResolution,
    CredentialResolver,
    CredentialStatus,
    CredentialType,
    IntegrationCapabilityError,
    IntegrationCredentialError,
    IntegrationPermissionError,
    IntegrationProvider,
    IntegrationProviderRegistry,
    IntegrationProviderUnavailableError,
    IntegrationRequest,
    IntegrationResponseStatus,
    IntegrationStatus,
    IntegrationValidationError,
    validate_provider_request,
)
from app.integrations.github import (
    SUPPORTED_CAPABILITIES,
    GitHubClient,
    GitHubProvider,
    translate_github_error,
)
from app.integrations.github.errors import (
    GitHubAuthenticationError,
    GitHubAuthorizationError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseParseError,
)


def _credential(**overrides: Any) -> CredentialReference:
    values: dict[str, Any] = {
        "provider_id": "github",
        "reference_id": "vault://credentials/github/user-001",
        "credential_type": CredentialType.oauth2,
        "ownership": CredentialOwnership(user_id="user-001", workspace_id="workspace-001"),
        "granted_scopes": ("repo:read",),
        "status": CredentialStatus.active,
    }
    values.update(overrides)
    return CredentialReference(**values)


def _request(**overrides: Any) -> IntegrationRequest:
    values: dict[str, Any] = {
        "request_id": "req-gh-001",
        "correlation_id": "corr-gh-001",
        "user_id": "user-001",
        "workspace_id": "workspace-001",
        "provider_id": "github",
        "capability": "repos.get",
        "requested_scopes": ("repo:read",),
        "credential": _credential(),
        "parameters": {"owner": "octocat", "repo": "Hello-World"},
        "metadata": {"test": "true"},
    }
    values.update(overrides)
    return IntegrationRequest(**values)


class MockTransport(httpx.AsyncBaseTransport):
    """Mock HTTP transport returning controlled responses."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


class FakeResolver(CredentialResolver):
    def __init__(self) -> None:
        self.resolve_count = 0

    async def resolve(self, reference: CredentialReference) -> CredentialResolution:
        self.resolve_count += 1
        return CredentialResolution(
            reference=reference,
            resolved_at=datetime.now(UTC),
            status=reference.status,
        )


def test_github_provider_implements_protocol_and_advertises_readonly_metadata() -> None:
    provider = GitHubProvider()
    assert isinstance(provider, IntegrationProvider)

    metadata = provider.metadata
    assert metadata.identity.provider_id == "github"
    assert metadata.identity.display_name == "GitHub"
    assert metadata.identity.version == "1.0"
    assert metadata.status == IntegrationStatus.available

    # Read-only capability set validation
    assert len(metadata.capabilities) == len(SUPPORTED_CAPABILITIES)
    cap_ids = {c.capability_id for c in metadata.capabilities}
    expected_caps = {
        "repos.list",
        "repos.get",
        "issues.list",
        "issues.get",
        "pulls.list",
        "pulls.get",
        "user.get",
    }
    assert cap_ids == expected_caps

    # Verify no write/destructive capabilities are advertised
    for cap in cap_ids:
        assert not any(
            write_word in cap
            for write_word in ("create", "update", "delete", "write", "merge", "push", "patch")
        )
        assert provider.supports_capability(cap)

    assert not provider.supports_capability("repos.create")
    assert not provider.supports_capability("issues.create")
    assert not provider.supports_capability("pulls.merge")

    # Verify permissions
    assert len(metadata.required_permissions) == 1
    assert metadata.required_permissions[0].scope_id == "repo:read"
    assert metadata.required_permissions[0].provider_id == "github"


def test_github_provider_registers_with_provider_registry() -> None:
    registry = IntegrationProviderRegistry()
    provider = GitHubProvider()

    registered_meta = registry.register(provider)
    assert registered_meta.identity.provider_id == "github"
    assert registry.count == 1
    assert registry.get("github") is provider
    assert registry.supports("github", "repos.get")
    assert not registry.supports("github", "repos.delete")

    # Discovery by capability and status
    discovered = registry.find(capability="issues.list", status=IntegrationStatus.available)
    assert len(discovered) == 1
    assert discovered[0].identity.provider_id == "github"


def test_validate_provider_request_enforces_boundaries() -> None:
    provider = GitHubProvider()

    # Valid request passes
    valid_req = _request()
    validate_provider_request(provider, valid_req)

    # Provider mismatch
    with pytest.raises(IntegrationValidationError, match="does not match"):
        validate_provider_request(provider, valid_req.model_copy(update={"provider_id": "slack"}))

    # Unsupported capability
    with pytest.raises(IntegrationCapabilityError, match="does not support 'repos.create'"):
        validate_provider_request(
            provider, valid_req.model_copy(update={"capability": "repos.create"})
        )

    # Missing required scopes
    with pytest.raises(IntegrationPermissionError, match="must explicitly declare required scopes"):
        validate_provider_request(provider, valid_req.model_copy(update={"requested_scopes": ()}))

    # Credential provider mismatch
    with pytest.raises(IntegrationCredentialError, match="credential reference provider"):
        validate_provider_request(
            provider,
            valid_req.model_copy(
                update={"credential": _credential(provider_id="slack", granted_scopes=())}
            ),
        )

    # Credential ownership mismatch
    with pytest.raises(IntegrationCredentialError, match="credential ownership does not match"):
        validate_provider_request(
            provider,
            valid_req.model_copy(
                update={
                    "credential": _credential(
                        ownership=CredentialOwnership(
                            user_id="diff-user",
                            workspace_id="workspace-001",
                        )
                    )
                }
            ),
        )

    # Unavailable provider
    unavailable_provider = GitHubProvider(status=IntegrationStatus.unavailable)
    with pytest.raises(
        IntegrationProviderUnavailableError,
        match="integration provider is unavailable",
    ):
        validate_provider_request(unavailable_provider, valid_req)


def test_credential_resolution_and_secret_boundary() -> None:
    secret_token = "synthetic-ghp-secret-token-xyz"
    token_resolved = False

    async def sample_token_resolver(ref: CredentialReference) -> str:
        nonlocal token_resolved
        token_resolved = True
        return secret_token

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == f"Bearer {secret_token}"
        assert request.headers.get("accept") == "application/vnd.github+json"
        assert request.headers.get("x-github-api-version") == "2022-11-28"
        return httpx.Response(
            status_code=200,
            json={
                "id": 12345,
                "name": "Hello-World",
                "full_name": "octocat/Hello-World",
                "owner": {"login": "octocat"},
                "html_url": "https://github.com/octocat/Hello-World",
            },
            headers={"x-ratelimit-remaining": "4999", "x-ratelimit-limit": "5000"},
        )

    transport = MockTransport(mock_handler)
    client = GitHubClient(client=httpx.AsyncClient(transport=transport))
    fake_resolver = FakeResolver()

    provider = GitHubProvider(
        client=client,
        credential_resolver=fake_resolver,
        token_resolver=sample_token_resolver,
    )

    req = _request(capability="repos.get")
    response = asyncio.run(provider.execute(req))

    assert response.status == IntegrationResponseStatus.succeeded
    assert token_resolved is True
    assert fake_resolver.resolve_count == 1

    # Ensure secret token is nowhere in response or metadata
    response_str = response.model_dump_json()
    assert secret_token not in response_str
    assert "Authorization" not in response_str


def test_execute_repos_list() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/octocat/repos"
        assert request.url.params["per_page"] == "10"
        return httpx.Response(
            status_code=200,
            json=[
                {
                    "id": 1,
                    "name": "repo-one",
                    "full_name": "octocat/repo-one",
                    "owner": {"login": "octocat"},
                    "private": False,
                    "html_url": "https://github.com/octocat/repo-one",
                },
                {
                    "id": 2,
                    "name": "repo-two",
                    "full_name": "octocat/repo-two",
                    "owner": {"login": "octocat"},
                    "private": True,
                    "html_url": "https://github.com/octocat/repo-two",
                },
            ],
            headers={"x-ratelimit-remaining": "4980"},
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    req = _request(
        capability="repos.list",
        parameters={"owner": "octocat", "per_page": 10},
    )
    res = asyncio.run(provider.execute(req))

    assert res.status == IntegrationResponseStatus.succeeded
    assert res.request_id == req.request_id
    assert res.correlation_id == req.correlation_id
    assert res.provider_id == "github"
    assert res.capability == "repos.list"
    assert res.result is not None
    assert res.result["count"] == 2
    assert len(res.result["repositories"]) == 2
    assert res.result["repositories"][0]["name"] == "repo-one"
    assert res.result["repositories"][1]["private"] is True
    assert res.metadata.get("x-ratelimit-remaining") == "4980"


def test_execute_issues_list_and_get() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World/issues/42":
            return httpx.Response(
                status_code=200,
                json={
                    "id": 4200,
                    "number": 42,
                    "title": "Bug in main loop",
                    "state": "open",
                    "user": {"login": "dev1"},
                    "html_url": "https://github.com/octocat/Hello-World/issues/42",
                    "labels": [{"name": "bug"}],
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/issues":
            # Return one issue and one PR to verify PR filtering
            return httpx.Response(
                status_code=200,
                json=[
                    {
                        "id": 4200,
                        "number": 42,
                        "title": "Bug in main loop",
                        "state": "open",
                        "user": {"login": "dev1"},
                        "html_url": "https://github.com/octocat/Hello-World/issues/42",
                    },
                    {
                        "id": 4201,
                        "number": 43,
                        "title": "Fix PR",
                        "pull_request": {"url": "https://api.github.com/repos/..."},
                    },
                ],
            )
        return httpx.Response(status_code=404)

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    # Test issues.list
    req_list = _request(
        capability="issues.list",
        parameters={"owner": "octocat", "repo": "Hello-World"},
    )
    res_list = asyncio.run(provider.execute(req_list))
    assert res_list.status == IntegrationResponseStatus.succeeded
    assert res_list.result is not None
    assert res_list.result["count"] == 1
    assert res_list.result["issues"][0]["number"] == 42

    # Test issues.get
    req_get = _request(
        capability="issues.get",
        parameters={"owner": "octocat", "repo": "Hello-World", "issue_number": 42},
    )
    res_get = asyncio.run(provider.execute(req_get))
    assert res_get.status == IntegrationResponseStatus.succeeded
    assert res_get.result is not None
    assert res_get.result["issue"]["title"] == "Bug in main loop"
    assert res_get.result["issue"]["labels"] == ("bug",)


def test_execute_pulls_list_and_get() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World/pulls/10":
            return httpx.Response(
                status_code=200,
                json={
                    "id": 9900,
                    "number": 10,
                    "title": "Add feature",
                    "state": "open",
                    "user": {"login": "author"},
                    "draft": False,
                    "html_url": "https://github.com/octocat/Hello-World/pull/10",
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/pulls":
            return httpx.Response(
                status_code=200,
                json=[
                    {
                        "id": 9900,
                        "number": 10,
                        "title": "Add feature",
                        "state": "open",
                        "user": {"login": "author"},
                        "draft": False,
                        "html_url": "https://github.com/octocat/Hello-World/pull/10",
                    }
                ],
            )
        return httpx.Response(status_code=404)

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    # Test pulls.list
    req_list = _request(
        capability="pulls.list",
        parameters={"owner": "octocat", "repo": "Hello-World"},
    )
    res_list = asyncio.run(provider.execute(req_list))
    assert res_list.status == IntegrationResponseStatus.succeeded
    assert res_list.result is not None
    assert res_list.result["count"] == 1
    assert res_list.result["pull_requests"][0]["number"] == 10

    # Test pulls.get
    req_get = _request(
        capability="pulls.get",
        parameters={"owner": "octocat", "repo": "Hello-World", "pull_number": 10},
    )
    res_get = asyncio.run(provider.execute(req_get))
    assert res_get.status == IntegrationResponseStatus.succeeded
    assert res_get.result is not None
    assert res_get.result["pull_request"]["title"] == "Add feature"


def test_execute_user_get() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user"
        return httpx.Response(
            status_code=200,
            json={
                "id": 583231,
                "login": "octocat",
                "name": "The Octocat",
                "type": "User",
                "html_url": "https://github.com/octocat",
                "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4",
            },
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    req = _request(capability="user.get", parameters={})
    res = asyncio.run(provider.execute(req))

    assert res.status == IntegrationResponseStatus.succeeded
    assert res.result is not None
    assert res.result["user"]["login"] == "octocat"
    assert res.result["user"]["name"] == "The Octocat"


def test_error_translation_authentication_401() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=401,
            json={"message": "Bad credentials", "documentation_url": "https://docs.github.com"},
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    res = asyncio.run(provider.execute(_request(capability="user.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "authentication_failed"
    assert res.error.retryable is False
    assert "Bad credentials" in res.error.message


def test_error_translation_forbidden_403() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=403,
            json={"message": "Resource not accessible by integration"},
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    res = asyncio.run(provider.execute(_request(capability="repos.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "forbidden"
    assert res.error.retryable is False


def test_error_translation_not_found_404() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=404,
            json={"message": "Not Found"},
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    res = asyncio.run(provider.execute(_request(capability="repos.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "resource_not_found"
    assert res.error.retryable is False


def test_error_translation_rate_limit_429_and_403() -> None:
    async def mock_handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=429,
            json={"message": "API rate limit exceeded"},
            headers={"retry-after": "60"},
        )

    client_429 = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler_429)))
    provider_429 = GitHubProvider(client=client_429)

    res = asyncio.run(provider_429.execute(_request(capability="repos.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "rate_limit_exceeded"
    assert res.error.retryable is True
    assert res.error.metadata.get("retry_after") == 60


def test_error_translation_network_timeout() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    res = asyncio.run(provider.execute(_request(capability="repos.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "network_failure"
    assert res.error.retryable is True


def test_error_translation_malformed_response() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=b"not-json-content",
            headers={"content-type": "text/html"},
        )

    client = GitHubClient(client=httpx.AsyncClient(transport=MockTransport(mock_handler)))
    provider = GitHubProvider(client=client)

    res = asyncio.run(provider.execute(_request(capability="repos.get")))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert res.error.code == "malformed_response"
    assert res.error.retryable is False


def test_missing_parameters_validation() -> None:
    provider = GitHubProvider()
    # repos.get requires owner and repo
    req = _request(capability="repos.get", parameters={})
    res = asyncio.run(provider.execute(req))
    assert res.status == IntegrationResponseStatus.failed
    assert res.error is not None
    assert "owner" in res.error.message.lower()


def test_translate_github_error_direct_helper() -> None:
    err_auth = GitHubAuthenticationError("Auth failed")
    translated_auth = translate_github_error(err_auth)
    assert translated_auth.code == "authentication_failed"
    assert translated_auth.retryable is False

    err_authz = GitHubAuthorizationError("Forbidden")
    translated_authz = translate_github_error(err_authz)
    assert translated_authz.code == "forbidden"

    err_nf = GitHubNotFoundError("Missing")
    translated_nf = translate_github_error(err_nf)
    assert translated_nf.code == "resource_not_found"

    err_rl = GitHubRateLimitError("Limit", retry_after=30)
    translated_rl = translate_github_error(err_rl)
    assert translated_rl.code == "rate_limit_exceeded"
    assert translated_rl.retryable is True
    assert translated_rl.metadata.get("retry_after") == 30

    err_net = GitHubNetworkError("Timeout")
    translated_net = translate_github_error(err_net)
    assert translated_net.code == "network_failure"
    assert translated_net.retryable is True

    err_parse = GitHubResponseParseError("Bad JSON")
    translated_parse = translate_github_error(err_parse)
    assert translated_parse.code == "malformed_response"

    err_unk = ValueError("Something unexpected")
    translated_unk = translate_github_error(err_unk)
    assert translated_unk.code == "internal_provider_error"
