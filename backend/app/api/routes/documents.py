from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_user,
    get_embedding_provider,
    get_vector_store,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.documents.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.domains.documents.schemas import DocumentListResponse, DocumentRead
from app.domains.documents.services import (
    DocumentDeleteService,
    DocumentIngestionService,
    DocumentNotFoundError,
    DocumentProcessingError,
    DocumentReadService,
    DocumentValidationError,
)
from app.domains.documents.vector_store import ChromaVectorStore, VectorStoreError
from app.domains.identity.models import User
from app.domains.identity.schemas import MessageResponse

router = APIRouter(prefix="/documents", tags=["documents"])
DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)
CURRENT_USER_DEP = Depends(get_current_user)
EMBEDDING_PROVIDER_DEP = Depends(get_embedding_provider)
VECTOR_STORE_DEP = Depends(get_vector_store)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    embedding_provider: EmbeddingProvider = EMBEDDING_PROVIDER_DEP,
    vector_store: ChromaVectorStore = VECTOR_STORE_DEP,
) -> DocumentRead:
    content = await file.read()
    service = DocumentIngestionService(
        db,
        settings,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    try:
        return await service.upload(
            current_user=current_user,
            filename=file.filename or "uploaded-document",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            request=request,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EmbeddingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (DocumentProcessingError, VectorStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    service = DocumentReadService(db, settings)
    return await service.list_documents(current_user=current_user, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> DocumentRead:
    service = DocumentReadService(db, settings)
    try:
        return await service.get_document(current_user=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc


@router.delete("/{document_id}", response_model=MessageResponse)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    vector_store: ChromaVectorStore = VECTOR_STORE_DEP,
) -> MessageResponse:
    service = DocumentDeleteService(db, settings, vector_store=vector_store)
    try:
        await service.delete(current_user=current_user, document_id=document_id, request=request)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc
    except VectorStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return MessageResponse(detail="document_deleted")
