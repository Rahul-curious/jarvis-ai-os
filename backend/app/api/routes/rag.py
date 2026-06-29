from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_user,
    get_embedding_provider,
    get_vector_store,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.documents.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.domains.documents.schemas import (
    RagQueryRequest,
    RagQueryResponse,
    RagSearchRequest,
    RagSearchResponse,
)
from app.domains.documents.services import RagQueryService, RagSearchService
from app.domains.documents.vector_store import ChromaVectorStore, VectorStoreError
from app.domains.identity.models import User

router = APIRouter(prefix="/rag", tags=["rag"])
DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)
CURRENT_USER_DEP = Depends(get_current_user)
EMBEDDING_PROVIDER_DEP = Depends(get_embedding_provider)
VECTOR_STORE_DEP = Depends(get_vector_store)


@router.post("/search", response_model=RagSearchResponse)
async def search_knowledge(
    payload: RagSearchRequest,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    embedding_provider: EmbeddingProvider = EMBEDDING_PROVIDER_DEP,
    vector_store: ChromaVectorStore = VECTOR_STORE_DEP,
) -> RagSearchResponse:
    service = RagSearchService(
        db,
        settings,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    try:
        return await service.search(current_user=current_user, payload=payload)
    except (EmbeddingProviderError, VectorStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/query", response_model=RagQueryResponse)
async def query_knowledge(
    payload: RagQueryRequest,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    embedding_provider: EmbeddingProvider = EMBEDDING_PROVIDER_DEP,
    vector_store: ChromaVectorStore = VECTOR_STORE_DEP,
) -> RagQueryResponse:
    service = RagQueryService(
        db,
        settings,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    try:
        return await service.query(current_user=current_user, payload=payload)
    except (EmbeddingProviderError, VectorStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
