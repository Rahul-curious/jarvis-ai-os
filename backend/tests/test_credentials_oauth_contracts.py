from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.integrations import (
    CredentialLifecycleError,
    CredentialOwnership,
    CredentialReference,
    CredentialResolution,
    CredentialResolver,
    CredentialRevocationRequest,
    CredentialRevocationResult,
    CredentialRevocationStatus,
    CredentialRevoker,
    CredentialStatus,
    CredentialType,
    IntegrationCapability,
    IntegrationCredentialError,
    IntegrationMetadata,
    IntegrationPermissionError,
    IntegrationProvider,
    IntegrationRequest,
    IntegrationResponseStatus,
    IntegrationValidationError,
    OAuthAuthorizationRequest,
    OAuthAuthorizationState,
    OAuthStateError,
    OAuthTokenResult,
    PermissionScope,
    ProviderIdentity,
    compare_scopes,
    ensure_credential_usable,
    validate_credential_transition,
    validate_oauth_state,
    validate_provider_request,
)


def _credential(**overrides: object) -> CredentialReference:
    values: dict[str, object] = {
        "provider_id": "example_provider",
        "reference_id": "vault://credentials/example-provider/default",
        "credential_type": CredentialType.oauth2,
        "ownership": CredentialOwnership(user_id="user-001", workspace_id="workspace-001"),
        "granted_scopes": ("records.read",),
    }
    values.update(overrides)
    return CredentialReference(**values)


def _oauth_state(**overrides: object) -> OAuthAuthorizationState:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "state_id": "state-001",
        "provider_id": "example_provider",
        "request_id": "oauth-request-001",
        "correlation_id": "trace-001",
        "user_id": "user-001",
        "workspace_id": "workspace-001",
        "created_at": now,
        "expires_at": now + timedelta(minutes=10),
    }
    values.update(overrides)
    return OAuthAuthorizationState(**values)


def _provider_metadata() -> IntegrationMetadata:
    return IntegrationMetadata(
        identity=ProviderIdentity(
            provider_id="example_provider",
            display_name="Example Provider",
            version="1.0",
        ),
        description="Synthetic provider metadata for contract tests.",
        capabilities=(IntegrationCapability(capability_id="read", description="Read records."),),
        required_permissions=(
            PermissionScope(
                provider_id="example_provider",
                scope_id="records.read",
                description="Read records.",
            ),
        ),
    )


class FakeProvider:
    metadata = _provider_metadata()

    def supports_capability(self, capability: str) -> bool:
        return any(item.capability_id == capability for item in self.metadata.capabilities)

    async def execute(self, request: IntegrationRequest):
        return request


class FakeResolver:
    async def resolve(self, reference: CredentialReference) -> CredentialResolution:
        return CredentialResolution(
            reference=reference,
            resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
            status=reference.status,
        )


class FakeRevoker:
    async def revoke(self, request: CredentialRevocationRequest) -> CredentialRevocationResult:
        return CredentialRevocationResult(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            provider_id=request.credential.provider_id,
            reference_id=request.credential.reference_id,
            status=CredentialRevocationStatus.accepted,
        )


def test_credential_lifecycle_states_are_explicit_and_non_active_states_are_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for status in CredentialStatus:
        reference = _credential(
            status=status,
            expires_at=now - timedelta(minutes=1) if status is CredentialStatus.expired else None,
        )
        if status is CredentialStatus.active:
            ensure_credential_usable(reference, now=now)
        else:
            with pytest.raises(CredentialLifecycleError):
                ensure_credential_usable(reference, now=now)

    with pytest.raises(IntegrationCredentialError):
        _credential(status=CredentialStatus.expired)

    with pytest.raises(CredentialLifecycleError):
        ensure_credential_usable(
            _credential(expires_at=now - timedelta(seconds=1)),
            now=now,
        )

    validate_credential_transition(CredentialStatus.pending, CredentialStatus.active)
    with pytest.raises(CredentialLifecycleError):
        validate_credential_transition(CredentialStatus.revoked, CredentialStatus.active)
    with pytest.raises(CredentialLifecycleError):
        validate_credential_transition(CredentialStatus.expired, CredentialStatus.active)


def test_credential_reference_validates_ownership_and_rejects_secret_fields() -> None:
    reference = _credential()
    assert reference.ownership is not None
    assert reference.granted_scopes == ("records.read",)
    assert "access_token" not in reference.model_dump()

    with pytest.raises(ValidationError):
        CredentialOwnership()

    with pytest.raises(IntegrationCredentialError):
        _credential(metadata={"refresh_token": "synthetic-test-value"})


def test_provider_request_checks_credential_provider_and_ownership() -> None:
    request = IntegrationRequest(
        request_id="request-001",
        user_id="user-001",
        workspace_id="workspace-001",
        provider_id="example_provider",
        capability="read",
        requested_scopes=("records.read",),
        credential=_credential(),
    )
    validate_provider_request(FakeProvider(), request)

    with pytest.raises(IntegrationCredentialError):
        validate_provider_request(
            FakeProvider(),
            request.model_copy(
                update={
                    "credential": _credential(ownership=CredentialOwnership(user_id="other-user"))
                }
            ),
        )

    with pytest.raises(IntegrationPermissionError):
        validate_provider_request(
            FakeProvider(),
            request.model_copy(update={"requested_scopes": ()}),
        )


def test_credential_resolver_and_revoker_are_async_protocols() -> None:
    resolver = FakeResolver()
    revoker = FakeRevoker()
    assert isinstance(FakeProvider(), IntegrationProvider)
    assert isinstance(resolver, CredentialResolver)
    assert isinstance(revoker, CredentialRevoker)

    resolution = asyncio.run(resolver.resolve(_credential()))
    revocation = asyncio.run(
        revoker.revoke(
            CredentialRevocationRequest(
                request_id="revoke-001",
                user_id="user-001",
                workspace_id="workspace-001",
                credential=_credential(),
            )
        )
    )

    assert resolution.reference.reference_id.startswith("vault://")
    assert revocation.status is CredentialRevocationStatus.accepted


def test_oauth_state_and_authorization_request_are_bound_and_expiration_aware() -> None:
    state = _oauth_state()
    request = OAuthAuthorizationRequest(
        request_id="oauth-request-001",
        correlation_id="trace-001",
        provider_id="example_provider",
        client_reference="client://jarvis/example",
        redirect_uri="https://app.example.test/oauth/callback",
        requested_scopes=("records.write", "records.read"),
        user_id="user-001",
        workspace_id="workspace-001",
        state=state,
    )

    validate_oauth_state(state, now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
    assert request.requested_scopes == ("records.read", "records.write")

    with pytest.raises(OAuthStateError):
        validate_oauth_state(state, now=datetime(2026, 1, 1, 0, 11, tzinfo=UTC))

    with pytest.raises(OAuthStateError):
        _oauth_state(expires_at=datetime(2026, 1, 1, 2, 0, tzinfo=UTC))

    with pytest.raises(OAuthStateError):
        OAuthAuthorizationRequest(
            request_id="oauth-request-001",
            provider_id="example_provider",
            client_reference="client://jarvis/example",
            redirect_uri="https://app.example.test/oauth/callback",
            requested_scopes=("records.read",),
            user_id="different-user",
            state=state,
        )


def test_scope_comparison_distinguishes_missing_and_unexpected_scopes() -> None:
    comparison = compare_scopes(
        requested=("records.write", "records.read"),
        granted=("records.read", "profile.read"),
    )

    assert comparison.requested == ("records.read", "records.write")
    assert comparison.granted == ("profile.read", "records.read")
    assert comparison.missing == ("records.write",)
    assert comparison.unexpected == ("profile.read",)
    assert comparison.is_satisfied is False


def test_token_result_and_revocation_result_never_model_plaintext_tokens() -> None:
    result = OAuthTokenResult(
        provider_id="example_provider",
        credential=_credential(),
        granted_scopes=("records.read",),
        refresh_available=True,
        expires_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        refresh_expires_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert "access_token" not in result.model_dump()
    assert "refresh_token" not in result.model_dump()

    with pytest.raises(IntegrationCredentialError):
        OAuthTokenResult(
            provider_id="other_provider",
            credential=_credential(),
        )

    with pytest.raises(IntegrationValidationError):
        CredentialRevocationResult(
            request_id="revoke-001",
            provider_id="example_provider",
            reference_id="vault://credentials/example-provider/default",
            status=CredentialRevocationStatus.failed,
        )


def test_phase_7_2_models_are_exported_from_integrations_package() -> None:
    assert CredentialStatus.active.value == "active"
    assert IntegrationResponseStatus.succeeded.value == "succeeded"
