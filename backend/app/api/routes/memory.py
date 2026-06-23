from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.domains.identity.models import User
from app.domains.memory.schemas import (
    MemoryCreateRequest,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryRead,
    MemoryReinforceRequest,
    MemorySearchRequest,
    MemoryType,
    MemoryUpdateRequest,
)
from app.domains.memory.services import (
    MemoryCreateService,
    MemoryNotFoundError,
    MemoryRecallService,
    MemoryReinforcementService,
    MemorySearchService,
    MemoryUpdateService,
    MemoryValidationError,
)

router = APIRouter(prefix="/memory", tags=["memory"])
DB_SESSION_DEP = Depends(get_db_session)
SETTINGS_DEP = Depends(get_settings)
CURRENT_USER_DEP = Depends(get_current_user)


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreateRequest,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryRead:
    service = MemoryCreateService(db, settings)
    try:
        return await service.create(current_user=current_user, payload=payload, request=request)
    except MemoryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
    memory_type: MemoryType | None = None,
    category: str | None = Query(default=None, min_length=1, max_length=120),
    include_expired: bool = False,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MemoryListResponse:
    service = MemorySearchService(db, settings)
    return await service.list_memories(
        current_user=current_user,
        memory_type=memory_type,
        category=category.strip() if category else None,
        include_expired=include_expired,
        limit=limit,
        offset=offset,
    )


@router.post("/search", response_model=MemoryListResponse)
async def search_memories(
    payload: MemorySearchRequest,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryListResponse:
    service = MemorySearchService(db, settings)
    return await service.search(current_user=current_user, payload=payload)


@router.post("/reinforce", response_model=MemoryRead)
async def reinforce_memory(
    payload: MemoryReinforceRequest,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryRead:
    service = MemoryReinforcementService(db, settings)
    try:
        return await service.reinforce(current_user=current_user, payload=payload, request=request)
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        ) from exc


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(
    memory_id: uuid.UUID,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryRead:
    service = MemoryRecallService(db, settings)
    try:
        return await service.recall(memory_id=memory_id, current_user=current_user, request=request)
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        ) from exc


@router.put("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdateRequest,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryRead:
    service = MemoryUpdateService(db, settings)
    try:
        return await service.update(
            memory_id=memory_id,
            current_user=current_user,
            payload=payload,
            request=request,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        ) from exc
    except MemoryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: uuid.UUID,
    request: Request,
    current_user: User = CURRENT_USER_DEP,
    db: AsyncSession = DB_SESSION_DEP,
    settings: Settings = SETTINGS_DEP,
) -> MemoryDeleteResponse:
    service = MemoryUpdateService(db, settings)
    try:
        await service.delete(memory_id=memory_id, current_user=current_user, request=request)
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        ) from exc
    return MemoryDeleteResponse(detail="memory_deleted")
