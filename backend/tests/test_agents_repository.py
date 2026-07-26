from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agents.repository import AgentRepository
from app.domains.identity.models import User


async def create_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        full_name="Agent Test User",
        password_hash="not-used-in-domain-tests",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def test_repository_creates_children_and_enforces_owner_scope(client) -> None:
    async def scenario() -> tuple[uuid.UUID, int, int, int, int]:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            owner = await create_user(session, "agent-owner@example.com")
            other_user = await create_user(session, "agent-other@example.com")
            repository = AgentRepository(session)
            definition = await repository.create_definition(
                user_id=owner.id,
                agent_key="assistant",
                name="Assistant",
                agent_type="assistant",
                description="Test assistant",
                version="1.0",
                configuration={"mode": "test"},
            )
            run = await repository.create_run(
                user_id=owner.id,
                agent_definition_id=definition.id,
                agent_type="assistant",
                task="Inspect the repository",
                input_metadata={"test": True},
            )
            step = await repository.create_step(
                run_id=run.id,
                user_id=owner.id,
                step_index=0,
                step_type="planning",
                name="Plan",
                status="pending",
                input_metadata={},
                output_metadata={},
                error_code=None,
                error_message=None,
            )
            await repository.create_event(
                run_id=run.id,
                user_id=owner.id,
                step_id=step.id,
                sequence=0,
                event_type="run.requested",
                status="requested",
                message="Requested",
                metadata={"source": "test"},
            )
            await repository.create_artifact(
                run_id=run.id,
                user_id=owner.id,
                artifact_type="text",
                name="notes.txt",
                content_type="text/plain",
                storage_uri="memory://notes.txt",
                checksum_sha256=None,
                size_bytes=10,
                metadata={},
            )
            await session.commit()

            persisted = await repository.get_run_for_user(run_id=run.id, user_id=owner.id)
            assert await repository.get_run_for_user(
                run_id=run.id,
                user_id=other_user.id,
            ) is None
            owner_runs, owner_total = await repository.list_runs_for_user(
                user_id=owner.id,
                status=None,
                limit=25,
                offset=0,
            )
            other_runs, other_total = await repository.list_runs_for_user(
                user_id=other_user.id,
                status=None,
                limit=25,
                offset=0,
            )
            assert persisted is not None
            return (
                persisted.id,
                len(persisted.steps),
                len(persisted.events),
                len(persisted.artifacts),
                owner_total + other_total + len(owner_runs) + len(other_runs),
            )

    run_id, step_count, event_count, artifact_count, scoped_count = asyncio.run(scenario())
    assert run_id is not None
    assert step_count == 1
    assert event_count == 1
    assert artifact_count == 1
    assert scoped_count == 2


def test_repository_definition_key_is_scoped_to_user(client) -> None:
    async def scenario() -> tuple[int, int]:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            first = await create_user(session, "agent-first@example.com")
            second = await create_user(session, "agent-second@example.com")
            repository = AgentRepository(session)
            await repository.create_definition(
                user_id=first.id,
                agent_key="researcher",
                name="Researcher",
                agent_type="research",
                description=None,
                version="1.0",
                configuration={},
            )
            await repository.create_definition(
                user_id=second.id,
                agent_key="researcher",
                name="Researcher",
                agent_type="research",
                description=None,
                version="1.0",
                configuration={},
            )
            await session.commit()
            first_definitions, first_total = await repository.list_definitions_for_user(
                user_id=first.id,
                include_archived=False,
                limit=25,
                offset=0,
            )
            second_definitions, second_total = await repository.list_definitions_for_user(
                user_id=second.id,
                include_archived=False,
                limit=25,
                offset=0,
            )
            return len(first_definitions) + len(second_definitions), first_total + second_total

    definition_count, total = asyncio.run(scenario())
    assert definition_count == 2
    assert total == 2


def test_repository_updates_and_deletes_user_scoped_resources(client) -> None:
    async def scenario() -> None:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            owner = await create_user(session, "agent-crud-owner@example.com")
            other_user = await create_user(session, "agent-crud-other@example.com")
            repository = AgentRepository(session)
            definition = await repository.create_definition(
                user_id=owner.id,
                agent_key="writer",
                name="Writer",
                agent_type="assistant",
                description=None,
                version="1.0",
                configuration={},
            )
            run = await repository.create_run(
                user_id=owner.id,
                agent_definition_id=definition.id,
                agent_type="assistant",
                task="Draft a summary",
                input_metadata={},
            )
            step = await repository.create_step(
                run_id=run.id,
                user_id=owner.id,
                step_index=0,
                step_type="draft",
                name="Draft summary",
                status="pending",
                input_metadata={},
                output_metadata={},
                error_code=None,
                error_message=None,
            )
            event = await repository.create_event(
                run_id=run.id,
                user_id=owner.id,
                step_id=step.id,
                sequence=0,
                event_type="step.requested",
                status="pending",
                message="Draft requested",
                metadata={},
            )
            artifact = await repository.create_artifact(
                run_id=run.id,
                user_id=owner.id,
                artifact_type="text",
                name="summary.txt",
                content_type="text/plain",
                storage_uri=None,
                checksum_sha256=None,
                size_bytes=0,
                metadata={},
            )

            await repository.update_definition(definition, name="Updated Writer")
            await repository.update_run(run, status="validating")
            await repository.update_step(step, status="running")
            await repository.update_event(event, message="Draft started")
            await repository.update_artifact(artifact, size_bytes=12)
            await session.commit()

            owner_definition = await repository.get_definition_for_user(
                definition_id=definition.id,
                user_id=owner.id,
            )
            owner_run = await repository.get_run_for_user(run_id=run.id, user_id=owner.id)
            owner_event = await repository.get_event_for_user(
                event_id=event.id,
                user_id=owner.id,
            )

            assert owner_definition is not None
            assert owner_definition.name == "Updated Writer"
            assert await repository.get_definition_for_user(
                definition_id=definition.id,
                user_id=other_user.id,
            ) is None
            assert owner_run is not None
            assert owner_run.status == "validating"
            assert await repository.get_step_for_user(
                step_id=step.id,
                user_id=other_user.id,
            ) is None
            assert owner_event is not None
            assert owner_event.message == "Draft started"
            assert await repository.get_artifact_for_user(
                artifact_id=artifact.id,
                user_id=other_user.id,
            ) is None

            await repository.delete_event(event)
            await repository.delete_artifact(artifact)
            await repository.delete_step(step)
            await session.commit()

            session.expunge_all()
            run_for_deletion = await repository.get_run_for_user(
                run_id=run.id,
                user_id=owner.id,
            )
            assert run_for_deletion is not None
            await repository.delete_run(run_for_deletion)
            await session.commit()

            definition_for_deletion = await repository.get_definition_for_user(
                definition_id=definition.id,
                user_id=owner.id,
                include_archived=True,
            )
            assert definition_for_deletion is not None
            await repository.delete_definition(definition_for_deletion)
            await session.commit()

            assert await repository.get_run_for_user(run_id=run.id, user_id=owner.id) is None
            assert await repository.get_definition_for_user(
                definition_id=definition.id,
                user_id=owner.id,
                include_archived=True,
            ) is None

    asyncio.run(scenario())
