from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.domains.agents.errors import (
    AgentConflictError,
    AgentDefinitionNotFoundError,
    AgentLifecycleError,
    AgentRunNotFoundError,
)
from app.domains.agents.schemas import (
    AgentArtifactCreateRequest,
    AgentDefinitionCreateRequest,
    AgentDefinitionUpdateRequest,
    AgentEventCreateRequest,
    AgentRunCreateRequest,
    AgentRunStatus,
    AgentRunStatusUpdateRequest,
    AgentStepCreateRequest,
)
from app.domains.agents.services import AgentDefinitionService, AgentRunService
from app.domains.identity.models import User


def authenticate_and_load_user(client, email: str) -> User:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Agent Service User",
            "email": email,
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201

    async def load() -> User:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == email))
            assert user is not None
            return user

    return asyncio.run(load())


def test_services_create_archive_and_reject_duplicate_definitions(client) -> None:
    user = authenticate_and_load_user(client, "agent-definition@example.com")

    async def scenario() -> None:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            service = AgentDefinitionService(session)
            payload = AgentDefinitionCreateRequest(
                agent_key="assistant",
                name="Assistant",
                agent_type="assistant",
                configuration={"mode": "controlled"},
            )
            definition = await service.create(current_user=user, payload=payload)
            assert definition.status == "active"

            with pytest.raises(AgentConflictError):
                await service.create(current_user=user, payload=payload)

            updated = await service.update(
                current_user=user,
                definition_id=definition.id,
                payload=AgentDefinitionUpdateRequest(name="Updated Assistant"),
            )
            assert updated.name == "Updated Assistant"

            await service.delete(current_user=user, definition_id=definition.id)
            with pytest.raises(AgentDefinitionNotFoundError):
                await service.get(current_user=user, definition_id=definition.id)

    asyncio.run(scenario())


def test_run_service_persists_lifecycle_children_and_owner_isolation(client) -> None:
    owner = authenticate_and_load_user(client, "agent-run-owner@example.com")
    other_user = authenticate_and_load_user(client, "agent-run-other@example.com")

    async def scenario() -> None:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            definition_service = AgentDefinitionService(session)
            run_service = AgentRunService(session)
            definition = await definition_service.create(
                current_user=owner,
                payload=AgentDefinitionCreateRequest(
                    agent_key="assistant",
                    name="Assistant",
                    agent_type="assistant",
                ),
            )
            run = await run_service.create(
                current_user=owner,
                payload=AgentRunCreateRequest(
                    agent_definition_id=definition.id,
                    agent_type="assistant",
                    task="Review the architecture",
                ),
            )
            assert run.status == AgentRunStatus.requested
            assert run.events[0].sequence == 0

            for next_status in (
                AgentRunStatus.validating,
                AgentRunStatus.queued,
                AgentRunStatus.running,
            ):
                run = await run_service.update_status(
                    current_user=owner,
                    run_id=run.id,
                    payload=AgentRunStatusUpdateRequest(status=next_status),
                )
            step = await run_service.append_step(
                current_user=owner,
                run_id=run.id,
                payload=AgentStepCreateRequest(
                    step_index=0,
                    step_type="planning",
                    name="Review architecture",
                ),
            )
            event = await run_service.append_event(
                current_user=owner,
                run_id=run.id,
                payload=AgentEventCreateRequest(
                    event_type="step.started",
                    step_id=step.id,
                    message="Step started",
                ),
            )
            artifact = await run_service.append_artifact(
                current_user=owner,
                run_id=run.id,
                payload=AgentArtifactCreateRequest(
                    artifact_type="text",
                    name="architecture-notes.txt",
                    size_bytes=12,
                ),
            )
            assert event.sequence == 4
            assert artifact.name == "architecture-notes.txt"

            completed = await run_service.update_status(
                current_user=owner,
                run_id=run.id,
                payload=AgentRunStatusUpdateRequest(
                    status=AgentRunStatus.succeeded,
                    output_text="Architecture review recorded.",
                ),
            )
            assert completed.status == AgentRunStatus.succeeded
            assert completed.completed_at is not None
            assert len(completed.steps) == 1
            assert len(completed.events) == 6
            assert len(completed.artifacts) == 1

            with pytest.raises(AgentLifecycleError):
                await run_service.update_status(
                    current_user=owner,
                    run_id=run.id,
                    payload=AgentRunStatusUpdateRequest(status=AgentRunStatus.running),
                )
            with pytest.raises(AgentRunNotFoundError):
                await run_service.get(current_user=other_user, run_id=run.id)

    asyncio.run(scenario())
