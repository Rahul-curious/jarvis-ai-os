from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agents.errors import (
    AgentConflictError,
    AgentDefinitionNotFoundError,
    AgentRunNotFoundError,
    AgentValidationError,
)
from app.domains.agents.models import (
    AgentArtifact,
    AgentDefinition,
    AgentEvent,
    AgentRun,
    AgentStep,
)
from app.domains.agents.policies import AgentPolicy
from app.domains.agents.repository import AgentRepository
from app.domains.agents.schemas import (
    AgentArtifactCreateRequest,
    AgentArtifactRead,
    AgentDefinitionCreateRequest,
    AgentDefinitionListResponse,
    AgentDefinitionRead,
    AgentDefinitionStatus,
    AgentDefinitionUpdateRequest,
    AgentEventCreateRequest,
    AgentEventRead,
    AgentRunCreateRequest,
    AgentRunListResponse,
    AgentRunRead,
    AgentRunStatus,
    AgentRunStatusUpdateRequest,
    AgentStepCreateRequest,
    AgentStepRead,
)
from app.domains.identity.models import User


def utc_now() -> datetime:
    return datetime.now(UTC)


def serialize_definition(definition: AgentDefinition) -> AgentDefinitionRead:
    return AgentDefinitionRead.model_validate(definition)


def serialize_step(step: AgentStep) -> AgentStepRead:
    return AgentStepRead.model_validate(step)


def serialize_event(event: AgentEvent) -> AgentEventRead:
    return AgentEventRead.model_validate(event)


def serialize_artifact(artifact: AgentArtifact) -> AgentArtifactRead:
    return AgentArtifactRead.model_validate(artifact)


def serialize_run(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        id=run.id,
        user_id=run.user_id,
        agent_definition_id=run.agent_definition_id,
        agent_type=run.agent_type,
        task=run.task,
        status=AgentRunStatus(run.status),
        input_metadata=run.input_metadata,
        output_text=run.output_text,
        output_metadata=run.output_metadata,
        error_code=run.error_code,
        error_message=run.error_message,
        retry_count=run.retry_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[serialize_step(step) for step in run.steps],
        events=[serialize_event(event) for event in run.events],
        artifacts=[serialize_artifact(artifact) for artifact in run.artifacts],
    )


def validate_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > 100:
        raise AgentValidationError("limit must be between 1 and 100")
    if offset < 0:
        raise AgentValidationError("offset must not be negative")


class AgentDefinitionService:
    def __init__(self, db: AsyncSession, policy: AgentPolicy | None = None) -> None:
        self.db = db
        self.policy = policy or AgentPolicy()
        self.repository = AgentRepository(db)

    async def create(
        self,
        *,
        current_user: User,
        payload: AgentDefinitionCreateRequest,
    ) -> AgentDefinitionRead:
        self.policy.validate_definition_create(payload)
        existing = await self.repository.get_definition_by_key_for_user(
            agent_key=payload.agent_key,
            user_id=current_user.id,
            include_archived=True,
        )
        if existing is not None:
            raise AgentConflictError("Agent key is already registered")

        definition = await self.repository.create_definition(
            user_id=current_user.id,
            agent_key=payload.agent_key,
            name=payload.name,
            agent_type=payload.agent_type,
            description=payload.description,
            version=payload.version,
            configuration=payload.configuration,
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AgentConflictError("Agent key is already registered") from exc
        await self.db.refresh(definition)
        return serialize_definition(definition)

    async def get(
        self,
        *,
        current_user: User,
        definition_id: uuid.UUID,
        include_archived: bool = False,
    ) -> AgentDefinitionRead:
        definition = await self.repository.get_definition_for_user(
            definition_id=definition_id,
            user_id=current_user.id,
            include_archived=include_archived,
        )
        if definition is None:
            raise AgentDefinitionNotFoundError("Agent definition not found")
        return serialize_definition(definition)

    async def list(
        self,
        *,
        current_user: User,
        limit: int = 25,
        offset: int = 0,
        include_archived: bool = False,
    ) -> AgentDefinitionListResponse:
        validate_pagination(limit=limit, offset=offset)
        definitions, total = await self.repository.list_definitions_for_user(
            user_id=current_user.id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return AgentDefinitionListResponse(
            items=[serialize_definition(definition) for definition in definitions],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update(
        self,
        *,
        current_user: User,
        definition_id: uuid.UUID,
        payload: AgentDefinitionUpdateRequest,
    ) -> AgentDefinitionRead:
        self.policy.validate_definition_update(payload)
        definition = await self.repository.get_definition_for_user(
            definition_id=definition_id,
            user_id=current_user.id,
            include_archived=True,
        )
        if definition is None:
            raise AgentDefinitionNotFoundError("Agent definition not found")

        updates = payload.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            updates["status"] = updates["status"].value
        if "agent_key" in updates:
            existing = await self.repository.get_definition_by_key_for_user(
                agent_key=updates["agent_key"],
                user_id=current_user.id,
                include_archived=True,
            )
            if existing is not None and existing.id != definition.id:
                raise AgentConflictError("Agent key is already registered")

        await self.repository.update_definition(definition, **updates)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AgentConflictError("Agent key is already registered") from exc
        await self.db.refresh(definition)
        return serialize_definition(definition)

    async def delete(
        self,
        *,
        current_user: User,
        definition_id: uuid.UUID,
    ) -> None:
        definition = await self.repository.get_definition_for_user(
            definition_id=definition_id,
            user_id=current_user.id,
        )
        if definition is None:
            raise AgentDefinitionNotFoundError("Agent definition not found")
        await self.repository.update_definition(
            definition,
            status=AgentDefinitionStatus.archived.value,
        )
        await self.db.commit()


class AgentRunService:
    def __init__(self, db: AsyncSession, policy: AgentPolicy | None = None) -> None:
        self.db = db
        self.policy = policy or AgentPolicy()
        self.repository = AgentRepository(db)

    async def create(
        self,
        *,
        current_user: User,
        payload: AgentRunCreateRequest,
    ) -> AgentRunRead:
        self.policy.validate_run_create(payload)
        definition = None
        if payload.agent_definition_id is not None:
            definition = await self.repository.get_definition_for_user(
                definition_id=payload.agent_definition_id,
                user_id=current_user.id,
            )
            if definition is None:
                raise AgentDefinitionNotFoundError("Agent definition not found")
            self.policy.ensure_definition_usable(definition.status)
            if definition.agent_type != payload.agent_type:
                raise AgentValidationError("Agent type does not match the selected definition")

        run = await self.repository.create_run(
            user_id=current_user.id,
            agent_definition_id=payload.agent_definition_id,
            agent_type=payload.agent_type,
            task=payload.task,
            input_metadata=payload.input_metadata,
        )
        await self.repository.create_event(
            run_id=run.id,
            user_id=current_user.id,
            step_id=None,
            sequence=0,
            event_type="run.requested",
            status=AgentRunStatus.requested.value,
            message="Agent run requested",
            metadata={},
        )
        await self.db.commit()
        persisted = await self.repository.get_run_for_user(
            run_id=run.id,
            user_id=current_user.id,
        )
        if persisted is None:
            raise AgentRunNotFoundError("Agent run was not persisted")
        return serialize_run(persisted)

    async def get(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
    ) -> AgentRunRead:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        return serialize_run(run)

    async def list(
        self,
        *,
        current_user: User,
        status: AgentRunStatus | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> AgentRunListResponse:
        validate_pagination(limit=limit, offset=offset)
        runs, total = await self.repository.list_runs_for_user(
            user_id=current_user.id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return AgentRunListResponse(
            items=[serialize_run(run) for run in runs],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        payload: AgentRunStatusUpdateRequest,
    ) -> AgentRunRead:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        previous_status = run.status
        self.policy.validate_status_transition(
            current_status=previous_status,
            target_status=payload.status,
        )

        updates: dict[str, Any] = {"status": payload.status.value}
        if payload.output_text is not None:
            updates["output_text"] = payload.output_text
        if payload.output_metadata is not None:
            self.policy.validate_event_metadata(payload.output_metadata)
            updates["output_metadata"] = payload.output_metadata
        if payload.error_code is not None:
            updates["error_code"] = payload.error_code
        if payload.error_message is not None:
            updates["error_message"] = payload.error_message
        if payload.increment_retry_count:
            updates["retry_count"] = run.retry_count + 1

        now = utc_now()
        if payload.status == AgentRunStatus.running and run.started_at is None:
            updates["started_at"] = now
        if payload.status in {
            AgentRunStatus.succeeded,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }:
            updates["completed_at"] = now

        await self.repository.update_run(run, **updates)
        sequence = await self.repository.next_event_sequence(run_id=run.id)
        await self.repository.create_event(
            run_id=run.id,
            user_id=current_user.id,
            step_id=None,
            sequence=sequence,
            event_type="run.status_changed",
            status=payload.status.value,
            message=f"Agent run transitioned to {payload.status.value}",
            metadata={"from": previous_status, "to": payload.status.value},
        )
        await self.db.commit()
        persisted = await self.repository.get_run_for_user(
            run_id=run.id,
            user_id=current_user.id,
        )
        if persisted is None:
            raise AgentRunNotFoundError("Agent run was not persisted")
        return serialize_run(persisted)

    async def append_step(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        payload: AgentStepCreateRequest,
    ) -> AgentStepRead:
        self.policy.validate_step_create(payload)
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        self.policy.validate_step_count(len(run.steps))
        step = await self.repository.create_step(
            run_id=run.id,
            user_id=current_user.id,
            step_index=payload.step_index,
            step_type=payload.step_type,
            name=payload.name,
            status=payload.status.value,
            input_metadata=payload.input_metadata,
            output_metadata=payload.output_metadata,
            error_code=payload.error_code,
            error_message=payload.error_message,
        )
        await self.db.commit()
        await self.db.refresh(step)
        return serialize_step(step)

    async def append_event(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        payload: AgentEventCreateRequest,
    ) -> AgentEventRead:
        self.policy.validate_event_metadata(payload.metadata)
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        self.policy.validate_event_count(len(run.events))
        if payload.step_id is not None:
            step = await self.repository.get_step_for_run(
                step_id=payload.step_id,
                run_id=run.id,
                user_id=current_user.id,
            )
            if step is None:
                raise AgentValidationError("Event step does not belong to the agent run")
        sequence = (
            payload.sequence
            if payload.sequence is not None
            else await self.repository.next_event_sequence(run_id=run.id)
        )
        event = await self.repository.create_event(
            run_id=run.id,
            user_id=current_user.id,
            step_id=payload.step_id,
            sequence=sequence,
            event_type=payload.event_type,
            status=payload.status,
            message=payload.message,
            metadata=payload.metadata,
        )
        await self.db.commit()
        await self.db.refresh(event)
        return serialize_event(event)

    async def append_artifact(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        payload: AgentArtifactCreateRequest,
    ) -> AgentArtifactRead:
        self.policy.validate_event_metadata(payload.metadata)
        self.policy.validate_artifact_size(payload.size_bytes)
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        artifact = await self.repository.create_artifact(
            run_id=run.id,
            user_id=current_user.id,
            artifact_type=payload.artifact_type,
            name=payload.name,
            content_type=payload.content_type,
            storage_uri=payload.storage_uri,
            checksum_sha256=payload.checksum_sha256,
            size_bytes=payload.size_bytes,
            metadata=payload.metadata,
        )
        await self.db.commit()
        await self.db.refresh(artifact)
        return serialize_artifact(artifact)

    async def delete(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
    ) -> None:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        await self.repository.delete_run(run)
        await self.db.commit()
