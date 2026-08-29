from fastapi import APIRouter

from app.api.routes import agents, auth, documents, health, memory, rag, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(memory.router)
api_router.include_router(documents.router)
api_router.include_router(rag.router)
api_router.include_router(agents.router)
