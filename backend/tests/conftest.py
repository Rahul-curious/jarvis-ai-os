from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import chromadb
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_embedding_provider, get_vector_store
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.domains.documents.embeddings import HashEmbeddingProvider
from app.domains.documents.vector_store import ChromaVectorStore
from app.main import create_app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    settings = Settings(
        jwt_secret_key="test-secret-key-for-auth-suite-32-chars",
        database_url="sqlite+aiosqlite:///:memory:",
        embedding_provider="hash",
        document_chunk_size=240,
        document_chunk_overlap=40,
    )
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def init_db() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_db() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_get_settings() -> Settings:
        return settings

    embedding_provider = HashEmbeddingProvider(dimensions=settings.embedding_dimensions)
    vector_store = ChromaVectorStore(
        client=chromadb.EphemeralClient(),
        collection_name=f"{settings.chroma_document_collection_name}_{id(engine)}",
    )

    def override_get_embedding_provider() -> HashEmbeddingProvider:
        return embedding_provider

    def override_get_vector_store() -> ChromaVectorStore:
        return vector_store

    asyncio.run(init_db())

    app = create_app(settings)
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_embedding_provider] = override_get_embedding_provider
    app.dependency_overrides[get_vector_store] = override_get_vector_store
    app.state.test_session_factory = session_factory
    app.state.test_vector_store = vector_store

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(drop_db())
