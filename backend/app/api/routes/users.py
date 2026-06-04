from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.domains.identity.models import User
from app.domains.identity.schemas import UserProfile

router = APIRouter(prefix="/users", tags=["users"])
CURRENT_USER_DEP = Depends(get_current_user)


@router.get("/me", response_model=UserProfile)
async def me(current_user: User = CURRENT_USER_DEP) -> UserProfile:
    return UserProfile.model_validate(current_user)
