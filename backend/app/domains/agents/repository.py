from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.agents.models import (
    AgentArtifact,
    AgentDefinition,
    AgentEvent,
    AgentRun,
    AgentStep,
)
from app.domains.agents.schemas import AgentDefinitionStatus, AgentRunStatus


class AgentRepository:
    """Thin persistence adapter for agent resources and their child records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_definition(
        self,
        *,
        user_id: uuid.UUID,
        agent_key: str,
        name: str,
        agent_type: str,
        description: str | None,
        version: str,
        configuration: dict[str, Any],
    ) -> AgentDefinition:
        definition = AgentDefinition(
            user_id=user_id,
            agent_key=agent_key,
            name=name,
            agent_type=agent_type,
            description=description,
            version=version,
            configuration=configuration,
        )
        self.db.add(definition)
        await self.db.flush()
        return definition

    async def get_definition_for_user(
        self,
        *,
        definition_id: uuid.UUID,
        user_id: uuid.UUID,
        include_archived: bool = False,
    ) -> AgentDefinition | None:
        statement = select(AgentDefinition).where(
            AgentDefinition.id == definition_id,
            AgentDefinition.user_id == user_id,
        )
        if not include_archived:
            statement = statement.where(AgentDefinition.status != AgentDefinitionStatus.archived)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_definition_by_key_for_user(
        self,
        *,
        agent_key: str,
        user_id: uuid.UUID,
        include_archived: bool = False,
    ) -> AgentDefinition | None:
        statement = select(AgentDefinition).where(
            AgentDefinition.agent_key == agent_key,
            AgentDefinition.user_id == user_id,
        )
        if not include_archived:
            statement = statement.where(AgentDefinition.status != AgentDefinitionStatus.archived)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_definitions_for_user(
        self,
        *,
        user_id: uuid.UUID,
        include_archived: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentDefinition], int]:
        filters = [AgentDefinition.user_id == user_id]
        if not include_archived:
            filters.append(AgentDefinition.status != AgentDefinitionStatus.archived)

        statement = (
            select(AgentDefinition)
            .where(*filters)
            .order_by(AgentDefinition.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count(AgentDefinition.id)).where(*filters)
        definitions_result = await self.db.execute(statement)
        count_result = await self.db.execute(count_statement)
        return list(definitions_result.scalars().all()), int(count_result.scalar_one() or 0)

    async def update_definition(
        self,
        definition: AgentDefinition,
        **updates: Any,
    ) -> AgentDefinition:
        for field_name, value in updates.items():
            setattr(definition, field_name, value)
        await self.db.flush()
        return definition

    async def delete_definition(self, definition: AgentDefinition) -> None:
        await self.db.delete(definition)
        await self.db.flush()

    async def create_run(
        self,
        *,
        user_id: uuid.UUID,
        agent_definition_id: uuid.UUID | None,
        agent_type: str,
        task: str,
        input_metadata: dict[str, Any],
    ) -> AgentRun:
        run = AgentRun(
            user_id=user_id,
            agent_definition_id=agent_definition_id,
            agent_type=agent_type,
            task=task,
            input_metadata=input_metadata,
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run_for_user(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentRun | None:
        statement = (
            select(AgentRun)
            .options(
                selectinload(AgentRun.definition),
                selectinload(AgentRun.steps),
                selectinload(AgentRun.events),
                selectinload(AgentRun.artifacts),
            )
            .execution_options(populate_existing=True)
            .where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_runs_for_user(
        self,
        *,
        user_id: uuid.UUID,
        status: AgentRunStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentRun], int]:
        filters = [AgentRun.user_id == user_id]
        if status is not None:
            filters.append(AgentRun.status == status.value)

        statement = (
            select(AgentRun)
            .options(
                selectinload(AgentRun.definition),
                selectinload(AgentRun.steps),
                selectinload(AgentRun.events),
                selectinload(AgentRun.artifacts),
            )
            .execution_options(populate_existing=True)
            .where(*filters)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count(AgentRun.id)).where(*filters)
        runs_result = await self.db.execute(statement)
        count_result = await self.db.execute(count_statement)
        return list(runs_result.scalars().unique().all()), int(count_result.scalar_one() or 0)

    async def update_run(
        self,
        run: AgentRun,
        **updates: Any,
    ) -> AgentRun:
        for field_name, value in updates.items():
            setattr(run, field_name, value)
        await self.db.flush()
        return run

    async def delete_run(self, run: AgentRun) -> None:
        await self.db.delete(run)
        await self.db.flush()

    async def create_step(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        step_index: int,
        step_type: str,
        name: str,
        status: str,
        input_metadata: dict[str, Any],
        output_metadata: dict[str, Any],
        error_code: str | None,
        error_message: str | None,
    ) -> AgentStep:
        step = AgentStep(
            run_id=run_id,
            user_id=user_id,
            step_index=step_index,
            step_type=step_type,
            name=name,
            status=status,
            input_metadata=input_metadata,
            output_metadata=output_metadata,
            error_code=error_code,
            error_message=error_message,
        )
        self.db.add(step)
        await self.db.flush()
        return step

    async def list_steps_for_run(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[AgentStep]:
        statement = (
            select(AgentStep)
            .join(AgentRun, AgentRun.id == AgentStep.run_id)
            .where(
                AgentStep.run_id == run_id,
                AgentStep.user_id == user_id,
                AgentRun.user_id == user_id,
            )
            .order_by(AgentStep.step_index)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def get_step_for_run(
        self,
        *,
        step_id: uuid.UUID,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentStep | None:
        statement = (
            select(AgentStep)
            .join(AgentRun, AgentRun.id == AgentStep.run_id)
            .where(
                AgentStep.id == step_id,
                AgentStep.run_id == run_id,
                AgentStep.user_id == user_id,
                AgentRun.user_id == user_id,
            )
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_step_for_user(
        self,
        *,
        step_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentStep | None:
        statement = (
            select(AgentStep)
            .join(AgentRun, AgentRun.id == AgentStep.run_id)
            .where(
                AgentStep.id == step_id,
                AgentStep.user_id == user_id,
                AgentRun.user_id == user_id,
            )
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def update_step(self, step: AgentStep, **updates: Any) -> AgentStep:
        for field_name, value in updates.items():
            setattr(step, field_name, value)
        await self.db.flush()
        return step

    async def delete_step(self, step: AgentStep) -> None:
        await self.db.delete(step)
        await self.db.flush()

    async def create_event(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        step_id: uuid.UUID | None,
        sequence: int,
        event_type: str,
        status: str | None,
        message: str | None,
        metadata: dict[str, Any],
    ) -> AgentEvent:
        event = AgentEvent(
            run_id=run_id,
            user_id=user_id,
            step_id=step_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            message=message,
            event_metadata=metadata,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def next_event_sequence(self, *, run_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run_id)
        )
        current_max = result.scalar_one_or_none()
        return int(current_max) + 1 if current_max is not None else 0

    async def list_events_for_run(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[list[AgentEvent], int]:
        filters = [
            AgentEvent.run_id == run_id,
            AgentEvent.user_id == user_id,
            AgentRun.user_id == user_id,
        ]
        statement = (
            select(AgentEvent)
            .join(AgentRun, AgentRun.id == AgentEvent.run_id)
            .where(*filters)
            .order_by(AgentEvent.sequence)
        )
        count_statement = (
            select(func.count(AgentEvent.id))
            .join(AgentRun, AgentRun.id == AgentEvent.run_id)
            .where(*filters)
        )
        events_result = await self.db.execute(statement)
        count_result = await self.db.execute(count_statement)
        return list(events_result.scalars().all()), int(count_result.scalar_one() or 0)

    async def get_event_for_user(
        self,
        *,
        event_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentEvent | None:
        statement = (
            select(AgentEvent)
            .join(AgentRun, AgentRun.id == AgentEvent.run_id)
            .where(
                AgentEvent.id == event_id,
                AgentEvent.user_id == user_id,
                AgentRun.user_id == user_id,
            )
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def update_event(self, event: AgentEvent, **updates: Any) -> AgentEvent:
        for field_name, value in updates.items():
            setattr(event, field_name, value)
        await self.db.flush()
        return event

    async def delete_event(self, event: AgentEvent) -> None:
        await self.db.delete(event)
        await self.db.flush()

    async def create_artifact(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        artifact_type: str,
        name: str,
        content_type: str | None,
        storage_uri: str | None,
        checksum_sha256: str | None,
        size_bytes: int,
        metadata: dict[str, Any],
    ) -> AgentArtifact:
        artifact = AgentArtifact(
            run_id=run_id,
            user_id=user_id,
            artifact_type=artifact_type,
            name=name,
            content_type=content_type,
            storage_uri=storage_uri,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            artifact_metadata=metadata,
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact

    async def list_artifacts_for_run(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[AgentArtifact]:
        statement = (
            select(AgentArtifact)
            .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
            .where(
                AgentArtifact.run_id == run_id,
                AgentArtifact.user_id == user_id,
                AgentRun.user_id == user_id,
            )
            .order_by(AgentArtifact.created_at)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def get_artifact_for_user(
        self,
        *,
        artifact_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentArtifact | None:
        statement = (
            select(AgentArtifact)
            .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
            .where(
                AgentArtifact.id == artifact_id,
                AgentArtifact.user_id == user_id,
                AgentRun.user_id == user_id,
            )
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def update_artifact(self, artifact: AgentArtifact, **updates: Any) -> AgentArtifact:
        for field_name, value in updates.items():
            setattr(artifact, field_name, value)
        await self.db.flush()
        return artifact

    async def delete_artifact(self, artifact: AgentArtifact) -> None:
        await self.db.delete(artifact)
        await self.db.flush()
