from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agents.context import AgentContextAssembler, ContextBuilder
from app.domains.agents.errors import (
    AgentConflictError,
    AgentDefinitionNotFoundError,
    AgentError,
    AgentRunNotFoundError,
    AgentValidationError,
)
from app.domains.agents.executor import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStepStatus,
    Executor,
)
from app.domains.agents.models import (
    AgentArtifact,
    AgentDefinition,
    AgentEvent,
    AgentRun,
    AgentStep,
)
from app.domains.agents.planner import ExecutionPlan, Planner, PlanningRequest
from app.domains.agents.policies import AgentPolicy
from app.domains.agents.repository import AgentRepository
from app.domains.agents.runtime import (
    AgentRuntime,
    RuntimeAgentDefinition,
    RuntimeContext,
    RuntimeResult,
    RuntimeStatus,
)
from app.domains.agents.schemas import (
    AgentArtifactCreateRequest,
    AgentArtifactRead,
    AgentConfiguration,
    AgentDefinitionCreateRequest,
    AgentDefinitionListResponse,
    AgentDefinitionRead,
    AgentDefinitionStatus,
    AgentDefinitionUpdateRequest,
    AgentEventCreateRequest,
    AgentEventListResponse,
    AgentEventRead,
    AgentRunCreateRequest,
    AgentRunListResponse,
    AgentRunRead,
    AgentRunStatus,
    AgentRunStatusUpdateRequest,
    AgentStepCreateRequest,
    AgentStepRead,
    AgentStepStatus,
    ContextAssemblyRequest,
    UserInformation,
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


class AgentAuditLogger(Protocol):
    """Infrastructure-provided audit sink used by API orchestration."""

    async def record(
        self,
        *,
        action: str,
        outcome: str,
        user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist one audit event without exposing request objects to the agent domain."""


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

    async def create_and_execute(
        self,
        *,
        current_user: User,
        payload: AgentRunCreateRequest,
        context_assembler: AgentContextAssembler,
        planner: Planner,
        executor: Executor,
        runtime: AgentRuntime,
        audit_logger: AgentAuditLogger | None = None,
    ) -> AgentRunRead:
        """Create a durable run and synchronously orchestrate completed Phase 6 contracts."""

        self.policy.validate_run_create(payload)
        definition = await self._resolve_definition(current_user=current_user, payload=payload)
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
            metadata={"request_id": payload.request_id},
        )
        await self._record_audit(
            audit_logger,
            action="agents.run.requested",
            outcome="success",
            user_id=current_user.id,
            resource_id=str(run.id),
            metadata={"agent_type": payload.agent_type, "request_id": payload.request_id},
        )
        await self.db.commit()

        try:
            await self._transition_run(
                run,
                current_user=current_user,
                status=AgentRunStatus.validating,
                message="Agent run validation started",
                audit_logger=audit_logger,
            )
            execution_context = await context_assembler.build_context(
                self._build_context_request(
                    run=run,
                    current_user=current_user,
                    payload=payload,
                    definition=definition,
                )
            )
            await self._append_run_event(
                run_id=run.id,
                user_id=current_user.id,
                event_type="context.assembled",
                status=AgentRunStatus.validating.value,
                message="Execution context assembled",
                metadata={
                    "provider_names": execution_context.metadata.provider_names,
                    "section_count": execution_context.metadata.section_count,
                    "total_size_bytes": execution_context.metadata.total_size_bytes,
                },
            )
            await self.db.commit()

            plan = await planner.plan(
                PlanningRequest(
                    task=payload.task,
                    context=execution_context,
                    requested_tool_ids=payload.requested_tool_ids,
                    metadata={"run_id": str(run.id), "request_id": payload.request_id},
                )
            )
            await self._append_run_event(
                run_id=run.id,
                user_id=current_user.id,
                event_type="planner.completed",
                status=AgentRunStatus.validating.value,
                message="Execution plan created",
                metadata={"plan_id": plan.plan_id, "step_count": len(plan.steps)},
            )
            await self.db.commit()

            await self._transition_run(
                run,
                current_user=current_user,
                status=AgentRunStatus.queued,
                message="Agent run queued for synchronous execution",
                audit_logger=audit_logger,
            )
            await self._transition_run(
                run,
                current_user=current_user,
                status=AgentRunStatus.running,
                message="Agent run execution started",
                audit_logger=audit_logger,
            )

            execution_result = await executor.execute(
                ExecutionRequest(
                    plan=plan,
                    request_id=payload.request_id,
                    metadata={"context_provider_names": execution_context.metadata.provider_names},
                )
            )
            await self._persist_execution_result(
                current_user=current_user,
                run_id=run.id,
                plan=plan,
                result=execution_result,
            )
            await self.db.commit()

            runtime_result = await runtime.execute(
                definition=self._build_runtime_definition(
                    run=run,
                    payload=payload,
                    definition=definition,
                ),
                context=RuntimeContext(
                    run_id=run.id,
                    user_id=current_user.id,
                    task=payload.task,
                    request_id=payload.request_id,
                    input_metadata={
                        **payload.input_metadata,
                        "agent_type": payload.agent_type,
                        "context_provider_names": execution_context.metadata.provider_names,
                        "context_size_bytes": execution_context.metadata.total_size_bytes,
                        "plan_id": plan.plan_id,
                        "execution_id": execution_result.execution_id,
                    },
                ),
            )
            await self._persist_runtime_result(
                current_user=current_user,
                run_id=run.id,
                result=runtime_result,
            )
            await self.db.commit()

            await self._transition_run(
                run,
                current_user=current_user,
                status=_agent_status_from_runtime(runtime_result.status),
                message=f"Agent runtime finished with status {runtime_result.status.value}",
                output_text=runtime_result.output_text,
                output_metadata=self._build_output_metadata(
                    context_provider_names=execution_context.metadata.provider_names,
                    context_size_bytes=execution_context.metadata.total_size_bytes,
                    plan=plan,
                    execution_result=execution_result,
                    runtime_result=runtime_result,
                    context_data=execution_context.data,
                ),
                error_code=runtime_result.error_code,
                error_message=runtime_result.error_message,
                increment_retry_count=runtime_result.retryable,
                audit_logger=audit_logger,
            )
        except Exception as exc:
            await self.db.rollback()
            if isinstance(exc, AgentError):
                message = str(exc) or "Agent run failed"
                error_code = exc.__class__.__name__
            else:
                message = "Agent run failed"
                error_code = "agent_run_failed"
            await self._fail_run_after_error(
                current_user=current_user,
                run_id=run.id,
                error_code=error_code,
                error_message=message,
                audit_logger=audit_logger,
            )
            if isinstance(exc, AgentError):
                raise
            raise

        persisted = await self.repository.get_run_for_user(run_id=run.id, user_id=current_user.id)
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

    async def list_events(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
    ) -> AgentEventListResponse:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        events, total = await self.repository.list_events_for_run(
            run_id=run_id,
            user_id=current_user.id,
        )
        return AgentEventListResponse(
            items=[serialize_event(event) for event in events],
            total=total,
        )

    async def cancel(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        runtime: AgentRuntime | None = None,
        executor: Executor | None = None,
        audit_logger: AgentAuditLogger | None = None,
    ) -> AgentRunRead:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            raise AgentRunNotFoundError("Agent run not found")
        if runtime is not None:
            await runtime.cancel(run_id)
        if executor is not None:
            await executor.cancel(run_id)
        await self._transition_run(
            run,
            current_user=current_user,
            status=AgentRunStatus.cancelled,
            message="Agent run cancelled",
            audit_logger=audit_logger,
        )
        persisted = await self.repository.get_run_for_user(run_id=run.id, user_id=current_user.id)
        if persisted is None:
            raise AgentRunNotFoundError("Agent run was not persisted")
        return serialize_run(persisted)

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

    async def _resolve_definition(
        self,
        *,
        current_user: User,
        payload: AgentRunCreateRequest,
    ) -> AgentDefinition | None:
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
        return definition

    def _build_context_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        payload: AgentRunCreateRequest,
        definition: AgentDefinition | None,
    ) -> ContextAssemblyRequest:
        configuration = self._agent_configuration(payload=payload, definition=definition)
        return (
            ContextBuilder()
            .with_run_id(run.id)
            .with_user_id(current_user.id)
            .with_task(payload.task)
            .with_request_id(payload.request_id)
            .with_memory_query(payload.memory_query)
            .with_knowledge_query(payload.knowledge_query)
            .with_conversation_history(payload.conversation_history)
            .with_runtime_metadata(
                {
                    "agent_type": payload.agent_type,
                    "agent_definition_id": str(payload.agent_definition_id)
                    if payload.agent_definition_id is not None
                    else None,
                    "request_id": payload.request_id,
                }
            )
            .with_user_information(
                UserInformation(
                    user_id=current_user.id,
                    email=current_user.email,
                    full_name=current_user.full_name,
                    is_active=current_user.is_active,
                )
            )
            .with_agent_configuration(configuration)
            .build()
        )

    def _agent_configuration(
        self,
        *,
        payload: AgentRunCreateRequest,
        definition: AgentDefinition | None,
    ) -> AgentConfiguration:
        if definition is not None:
            return AgentConfiguration(
                agent_id=definition.id,
                agent_key=definition.agent_key,
                agent_type=definition.agent_type,
                version=definition.version,
                configuration=definition.configuration,
            )
        return AgentConfiguration(
            agent_id=None,
            agent_key=payload.agent_type,
            agent_type=payload.agent_type,
            version="1.0",
            configuration={},
        )

    def _build_runtime_definition(
        self,
        *,
        run: AgentRun,
        payload: AgentRunCreateRequest,
        definition: AgentDefinition | None,
    ) -> RuntimeAgentDefinition:
        if definition is not None:
            return RuntimeAgentDefinition(
                id=definition.id,
                agent_key=definition.agent_key,
                agent_type=definition.agent_type,
                version=definition.version,
                configuration=definition.configuration,
            )
        return RuntimeAgentDefinition(
            id=run.id,
            agent_key=payload.agent_type,
            agent_type=payload.agent_type,
            version="1.0",
            configuration={},
        )

    async def _transition_run(
        self,
        run: AgentRun,
        *,
        current_user: User,
        status: AgentRunStatus,
        message: str,
        audit_logger: AgentAuditLogger | None,
        output_text: str | None = None,
        output_metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        increment_retry_count: bool = False,
    ) -> None:
        previous_status = run.status
        self.policy.validate_status_transition(current_status=previous_status, target_status=status)
        updates: dict[str, Any] = {"status": status.value}
        if output_text is not None:
            updates["output_text"] = output_text
        if output_metadata is not None:
            self.policy.validate_event_metadata(output_metadata)
            updates["output_metadata"] = output_metadata
        if error_code is not None:
            updates["error_code"] = error_code
        if error_message is not None:
            updates["error_message"] = error_message
        if increment_retry_count:
            updates["retry_count"] = run.retry_count + 1

        now = utc_now()
        if status == AgentRunStatus.running and run.started_at is None:
            updates["started_at"] = now
        if status in {
            AgentRunStatus.succeeded,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }:
            updates["completed_at"] = now

        await self.repository.update_run(run, **updates)
        await self._append_run_event(
            run_id=run.id,
            user_id=current_user.id,
            event_type="run.status_changed",
            status=status.value,
            message=message,
            metadata={"from": previous_status, "to": status.value},
        )
        await self._record_audit(
            audit_logger,
            action=_audit_action_for_status(status),
            outcome="success",
            user_id=current_user.id,
            resource_id=str(run.id),
            metadata={"from": previous_status, "to": status.value},
        )
        await self.db.commit()

    async def _append_run_event(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        event_type: str,
        status: str | None,
        message: str | None,
        metadata: dict[str, Any],
        step_id: uuid.UUID | None = None,
    ) -> AgentEvent:
        sequence = await self.repository.next_event_sequence(run_id=run_id)
        return await self.repository.create_event(
            run_id=run_id,
            user_id=user_id,
            step_id=step_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            message=message,
            metadata=metadata,
        )

    async def _persist_execution_result(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        plan: ExecutionPlan,
        result: ExecutionResult,
    ) -> None:
        steps_by_id = {step.step_id: step for step in plan.steps}
        for state in result.state.step_states:
            step = steps_by_id[state.step_id]
            await self.repository.create_step(
                run_id=run_id,
                user_id=current_user.id,
                step_index=state.order - 1,
                step_type=step.step_type.value,
                name=_truncate(step.description, 160),
                status=_agent_step_status_from_execution(state.status).value,
                input_metadata={
                    "plan_step_id": step.step_id,
                    "tool_id": step.tool_id,
                    "depends_on": step.depends_on,
                },
                output_metadata={
                    "execution_status": state.status.value,
                    "started_at": state.started_at.isoformat() if state.started_at else None,
                    "completed_at": state.completed_at.isoformat() if state.completed_at else None,
                },
                error_code=state.error_code,
                error_message=state.error_message,
            )
        for event in result.events:
            await self._append_run_event(
                run_id=run_id,
                user_id=current_user.id,
                event_type=event.event_type,
                status=event.status.value if event.status is not None else None,
                message=event.message,
                metadata={
                    **event.metadata,
                    "executor_sequence": event.sequence,
                    "executor_step_id": event.step_id,
                },
            )

    async def _persist_runtime_result(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        result: RuntimeResult,
    ) -> None:
        for event in result.events:
            await self._append_run_event(
                run_id=run_id,
                user_id=current_user.id,
                event_type=event.event_type,
                status=event.status.value if event.status is not None else None,
                message=event.message,
                metadata={**event.metadata, "runtime_sequence": event.sequence},
            )

    def _build_output_metadata(
        self,
        *,
        context_provider_names: tuple[str, ...],
        context_size_bytes: int,
        plan: ExecutionPlan,
        execution_result: ExecutionResult,
        runtime_result: RuntimeResult,
        context_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "context": {
                "provider_names": context_provider_names,
                "total_size_bytes": context_size_bytes,
                "memory_count": context_data.get("memory_count", 0),
                "knowledge_count": context_data.get("knowledge_count", 0),
                "knowledge_citations": context_data.get("knowledge_citations", []),
            },
            "planner": {
                "plan_id": plan.plan_id,
                "step_count": len(plan.steps),
                "metadata": plan.metadata.model_dump(mode="json"),
            },
            "executor": {
                "execution_id": execution_result.execution_id,
                "status": execution_result.status.value,
                "metadata": execution_result.output_metadata,
            },
            "runtime": {
                "status": runtime_result.status.value,
                "metadata": runtime_result.output_metadata,
                "retryable": runtime_result.retryable,
            },
        }

    async def _fail_run_after_error(
        self,
        *,
        current_user: User,
        run_id: uuid.UUID,
        error_code: str,
        error_message: str,
        audit_logger: AgentAuditLogger | None,
    ) -> None:
        run = await self.repository.get_run_for_user(run_id=run_id, user_id=current_user.id)
        if run is None:
            return
        if AgentRunStatus(run.status) == AgentRunStatus.requested:
            await self._transition_run(
                run,
                current_user=current_user,
                status=AgentRunStatus.validating,
                message="Agent run validation started",
                audit_logger=audit_logger,
            )
        if AgentRunStatus(run.status) in {
            AgentRunStatus.succeeded,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }:
            return
        await self._transition_run(
            run,
            current_user=current_user,
            status=AgentRunStatus.failed,
            message="Agent run failed",
            error_code=error_code,
            error_message=error_message,
            audit_logger=audit_logger,
        )

    async def _record_audit(
        self,
        audit_logger: AgentAuditLogger | None,
        *,
        action: str,
        outcome: str,
        user_id: uuid.UUID | None,
        resource_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if audit_logger is None:
            return
        await audit_logger.record(
            action=action,
            outcome=outcome,
            user_id=user_id,
            resource_type="agent_run" if resource_id is not None else None,
            resource_id=resource_id,
            metadata=metadata,
        )


def _agent_status_from_runtime(status: RuntimeStatus) -> AgentRunStatus:
    return {
        RuntimeStatus.succeeded: AgentRunStatus.succeeded,
        RuntimeStatus.failed: AgentRunStatus.failed,
        RuntimeStatus.cancelled: AgentRunStatus.cancelled,
        RuntimeStatus.retriable: AgentRunStatus.retriable,
    }.get(status, AgentRunStatus.failed)


def _agent_step_status_from_execution(status: ExecutionStepStatus) -> AgentStepStatus:
    return {
        ExecutionStepStatus.pending: AgentStepStatus.pending,
        ExecutionStepStatus.running: AgentStepStatus.running,
        ExecutionStepStatus.completed: AgentStepStatus.succeeded,
        ExecutionStepStatus.deferred: AgentStepStatus.skipped,
        ExecutionStepStatus.failed: AgentStepStatus.failed,
        ExecutionStepStatus.cancelled: AgentStepStatus.cancelled,
    }[status]


def _audit_action_for_status(status: AgentRunStatus) -> str:
    if status == AgentRunStatus.running:
        return "agents.run.started"
    return f"agents.run.{status.value}"


def _truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else value[: max_length - 3].rstrip() + "..."
