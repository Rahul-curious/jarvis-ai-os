from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.documents.models import Document, DocumentChunk


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_document(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        file_size_bytes: int,
        checksum_sha256: str,
        text_length: int,
        embedding_model: str,
        vector_collection: str,
        metadata: dict,
    ) -> Document:
        document = Document(
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            checksum_sha256=checksum_sha256,
            text_length=text_length,
            embedding_model=embedding_model,
            vector_collection=vector_collection,
            document_metadata=metadata,
        )
        self.db.add(document)
        await self.db.flush()
        return document

    async def create_chunks(
        self,
        *,
        document: Document,
        chunks: Sequence[dict],
    ) -> list[DocumentChunk]:
        db_chunks: list[DocumentChunk] = []
        for chunk in chunks:
            db_chunk = DocumentChunk(
                document_id=document.id,
                user_id=document.user_id,
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                char_count=chunk["char_count"],
                content_hash=chunk["content_hash"],
                vector_id=chunk["vector_id"],
                chunk_metadata=chunk["metadata"],
            )
            self.db.add(db_chunk)
            db_chunks.append(db_chunk)
        await self.db.flush()
        return db_chunks

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        statement = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.user_id == user_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count(Document.id)).where(
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
        )
        documents_result = await self.db.execute(statement)
        count_result = await self.db.execute(count_statement)
        return list(documents_result.scalars().unique().all()), int(count_result.scalar_one() or 0)

    async def get_for_user(
        self,
        *,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Document | None:
        statement = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id, Document.user_id == user_id)
        )
        if not include_deleted:
            statement = statement.where(Document.deleted_at.is_(None))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_chunks_by_ids(
        self,
        *,
        chunk_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> list[DocumentChunk]:
        if not chunk_ids:
            return []
        statement = (
            select(DocumentChunk)
            .options(selectinload(DocumentChunk.document))
            .join(Document)
            .where(
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.user_id == user_id,
                Document.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(statement)
        chunks_by_id = {chunk.id: chunk for chunk in result.scalars().unique().all()}
        return [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]

    async def soft_delete(self, document: Document) -> None:
        document.deleted_at = datetime.now(UTC)
        await self.db.flush()
