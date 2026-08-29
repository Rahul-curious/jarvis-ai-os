from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AGENT_EXECUTOR_DEP,
    AGENT_PLANNER_DEP,
    AGENT_RUNTIME_DEP,
    get_current_user,
    get_embedding_provider,
    get_vector_store,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.agents.context import (
    AgentConfigurationProvider,
    AgentContextAssembler,
    ConversationHistoryProvider,
    RuntimeMetadataProvider,
    UserInformationProvider,
)
from app.domains.agents.errors import (
    AgentAuthorizationError,
    AgentContextError,
    AgentKnowledgeProviderError,
    AgentMemoryProviderError,
    AgentNotFoundError,
    AgentPolicyDeniedError,
    AgentRuntimeError,
    AgentValidationError,
)
from app.domains.agents.executor import Executor
from app.domains.agents.knowledge import KnowledgeContextProvider
from app.domains.agents.memory import MemoryContextProvider
from app.domains.agents.planner import Planner
from app.domains.agents.runtime import AgentRuntime
from app.domains.agents.schemas import (
    AgentEventListResponse,
    AgentRunCreateRequest,
    AgentRunListResponse,
    AgentRunRead,
    AgentRunStatus,
)
from app.domains.agents.services import AgentRunService
from app.domains.documents.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.domains.documents.services import RagQueryService
from app.domains.documents.vector_store import ChromaVectorStore, VectorStoreError
from app.domains.governance.audit import record_audit_event
from app.domains.identity.models import User
from app.domains.memory.services import MemorySearchService

router = APIRouter(prefix="/agents", tags=["agents"])
DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)
CURRENT_USER_DEP = Depends(get_current_user)
EMBEDDING_PROVIDER_DEP = Depends(get_embedding_provider)
VECTOR_STORE_DEP = Depends(get_vector_store)
RUN_STATUS_QUERY = Query(default=None, alias="status")
RUN_LIMIT_QUERY = Query(default=25, ge=1, le=100)
RUN_OFFSET_QUERY = Query(default=0, ge=0)


class RequestAuditLogger:
    def __init__(self, db: AsyncSession, request: Request) -> None:
        self.db = db
        self.request = request

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
        await record_audit_event(
            self.db,
            action=action,
            outcome=outcome,
            request=self.request,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )


@router.post("/runs", response_model=AgentRunRead, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    embedding_provider: EmbeddingProvider = EMBEDDING_PROVIDER_DEP,
    vector_store: ChromaVectorStore = VECTOR_STORE_DEP,
    planner: Planner = AGENT_PLANNER_DEP,
    executor: Executor = AGENT_EXECUTOR_DEP,
    runtime: AgentRuntime = AGENT_RUNTIME_DEP,
) -> AgentRunRead:
    service = AgentRunService(db)
    assembler = _build_context_assembler(
        db=db,
        settings=settings,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    try:
        return await service.create_and_execute(
            current_user=current_user,
            payload=payload,
            context_assembler=assembler,
            planner=planner,
            executor=executor,
            runtime=runtime,
            audit_logger=RequestAuditLogger(db, request),
        )
    except (AgentKnowledgeProviderError, AgentMemoryProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (EmbeddingProviderError, VectorStoreError, AgentRuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (AgentAuthorizationError, AgentPolicyDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (AgentContextError, AgentValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs", response_model=AgentRunListResponse)
async def list_agent_runs(
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    run_status: AgentRunStatus | None = RUN_STATUS_QUERY,
    limit: int = RUN_LIMIT_QUERY,
    offset: int = RUN_OFFSET_QUERY,
) -> AgentRunListResponse:
    service = AgentRunService(db)
    try:
        return await service.list(
            current_user=current_user,
            status=run_status,
            limit=limit,
            offset=offset,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=AgentRunRead)
async def get_agent_run(
    run_id: uuid.UUID,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
) -> AgentRunRead:
    service = AgentRunService(db)
    try:
        return await service.get(current_user=current_user, run_id=run_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_agent_run(
    run_id: uuid.UUID,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    executor: Executor = AGENT_EXECUTOR_DEP,
    runtime: AgentRuntime = AGENT_RUNTIME_DEP,
) -> AgentRunRead:
    service = AgentRunService(db)
    try:
        return await service.cancel(
            current_user=current_user,
            run_id=run_id,
            executor=executor,
            runtime=runtime,
            audit_logger=RequestAuditLogger(db, request),
        )
    except (AgentAuthorizationError, AgentPolicyDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=AgentEventListResponse)
async def list_agent_run_events(
    run_id: uuid.UUID,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
) -> AgentEventListResponse:
    service = AgentRunService(db)
    try:
        return await service.list_events(current_user=current_user, run_id=run_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _build_context_assembler(
    *,
    db: AsyncSession,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    vector_store: ChromaVectorStore,
) -> AgentContextAssembler:
    memory_service = MemorySearchService(db, settings)
    rag_service = RagQueryService(
        db,
        settings,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    return AgentContextAssembler(
        providers=[
            ConversationHistoryProvider(),
            RuntimeMetadataProvider(),
            UserInformationProvider(),
            AgentConfigurationProvider(),
            MemoryContextProvider(memory_service),
            KnowledgeContextProvider(rag_service),
        ],
        required_provider_names={
            "conversation_history",
            "runtime_metadata",
            "user_information",
            "agent_configuration",
            "memory",
            "knowledge",
        },
    )
