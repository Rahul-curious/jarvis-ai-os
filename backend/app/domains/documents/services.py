from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domains.documents.chunking import TextChunker
from app.domains.documents.embeddings import EmbeddingProvider
from app.domains.documents.models import Document
from app.domains.documents.parser import DocumentParser, DocumentParsingError
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.schemas import (
    DocumentListResponse,
    DocumentRead,
    RagCitation,
    RagQueryRequest,
    RagQueryResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResult,
)
from app.domains.documents.vector_store import ChromaVectorStore, VectorRecord, VectorStoreError
from app.domains.governance.audit import record_audit_event
from app.domains.identity.models import User


class DocumentNotFoundError(Exception):
    """Raised when a document cannot be found for the authenticated user."""


class DocumentValidationError(Exception):
    """Raised when document input is invalid."""


class DocumentProcessingError(Exception):
    """Raised when ingestion or retrieval processing fails."""


def serialize_document(document: Document) -> DocumentRead:
    return DocumentRead.model_validate(document)


class BaseDocumentService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repository = DocumentRepository(db)

    async def _record_audit(
        self,
        *,
        action: str,
        request: Request,
        user_id: uuid.UUID,
        document_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await record_audit_event(
            self.db,
            action=action,
            outcome="success",
            request=request,
            user_id=user_id,
            resource_type="document" if document_id else None,
            resource_id=str(document_id) if document_id else None,
            metadata=metadata,
        )


class DocumentIngestionService(BaseDocumentService):
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: ChromaVectorStore,
    ) -> None:
        super().__init__(db, settings)
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.parser = DocumentParser()
        self.chunker = TextChunker(
            chunk_size=settings.document_chunk_size,
            chunk_overlap=settings.document_chunk_overlap,
        )

    async def upload(
        self,
        *,
        current_user: User,
        filename: str,
        content_type: str,
        content: bytes,
        request: Request,
    ) -> DocumentRead:
        if not filename.strip():
            raise DocumentValidationError("filename is required")
        if not content:
            raise DocumentValidationError("document is empty")
        if len(content) > self.settings.document_max_upload_bytes:
            raise DocumentValidationError("document exceeds max upload size")

        checksum = hashlib.sha256(content).hexdigest()
        try:
            parsed = self.parser.parse(filename=filename, content=content)
            chunks = self.chunker.chunk(parsed.text)
        except DocumentParsingError as exc:
            raise DocumentValidationError(str(exc)) from exc

        if not chunks:
            raise DocumentValidationError("document did not produce any chunks")

        document: Document | None = None
        vectors_written = False
        vector_ids_written: list[str] = []
        try:
            document = await self.repository.create_document(
                user_id=current_user.id,
                filename=filename.strip(),
                content_type=content_type or "application/octet-stream",
                file_size_bytes=len(content),
                checksum_sha256=checksum,
                text_length=len(parsed.text),
                embedding_model=self.embedding_provider.model_name,
                vector_collection=self.vector_store.collection_name,
                metadata={
                    "parser": parsed.parser_name,
                    "parser_metadata": parsed.metadata,
                },
            )
            chunk_payloads = [
                {
                    "chunk_index": chunk.index,
                    "content": chunk.content,
                    "char_count": chunk.char_count,
                    "content_hash": chunk.content_hash,
                    "vector_id": f"document:{document.id}:chunk:{chunk.index}",
                    "metadata": {"parser": parsed.parser_name},
                }
                for chunk in chunks
            ]
            db_chunks = await self.repository.create_chunks(
                document=document,
                chunks=chunk_payloads,
            )
            embeddings = self.embedding_provider.embed_texts([chunk.content for chunk in chunks])
            records = [
                VectorRecord(
                    vector_id=db_chunk.vector_id,
                    document_id=document.id,
                    chunk_id=db_chunk.id,
                    user_id=current_user.id,
                    chunk_index=db_chunk.chunk_index,
                    filename=document.filename,
                    content=db_chunk.content,
                    embedding=embeddings[index],
                )
                for index, db_chunk in enumerate(db_chunks)
            ]
            self.vector_store.upsert(records)
            vectors_written = True
            vector_ids_written = [record.vector_id for record in records]

            document.chunk_count = len(db_chunks)
            document.status = "indexed"
            await self._record_audit(
                action="documents.upload",
                request=request,
                user_id=current_user.id,
                document_id=document.id,
                metadata={"filename": document.filename, "chunk_count": len(db_chunks)},
            )
            await self.db.commit()
            refreshed = await self.repository.get_for_user(
                document_id=document.id,
                user_id=current_user.id,
            )
            return serialize_document(refreshed or document)
        except VectorStoreError as exc:
            await self.db.rollback()
            raise DocumentProcessingError(str(exc)) from exc
        except Exception:
            await self.db.rollback()
            if vectors_written and document is not None:
                self.vector_store.delete_document(
                    document_id=document.id,
                    user_id=current_user.id,
                    vector_ids=vector_ids_written,
                )
            raise


class DocumentReadService(BaseDocumentService):
    async def list_documents(
        self,
        *,
        current_user: User,
        limit: int,
        offset: int,
    ) -> DocumentListResponse:
        documents, total = await self.repository.list_for_user(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return DocumentListResponse(
            items=[serialize_document(document) for document in documents],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_document(self, *, current_user: User, document_id: uuid.UUID) -> DocumentRead:
        document = await self.repository.get_for_user(
            document_id=document_id,
            user_id=current_user.id,
        )
        if document is None:
            raise DocumentNotFoundError("Document not found")
        return serialize_document(document)


class DocumentDeleteService(BaseDocumentService):
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        vector_store: ChromaVectorStore,
    ) -> None:
        super().__init__(db, settings)
        self.vector_store = vector_store

    async def delete(
        self,
        *,
        current_user: User,
        document_id: uuid.UUID,
        request: Request,
    ) -> None:
        document = await self.repository.get_for_user(
            document_id=document_id,
            user_id=current_user.id,
        )
        if document is None:
            raise DocumentNotFoundError("Document not found")

        self.vector_store.delete_document(
            document_id=document.id,
            user_id=current_user.id,
            vector_ids=[chunk.vector_id for chunk in document.chunks],
        )
        await self.repository.soft_delete(document)
        await self._record_audit(
            action="documents.delete",
            request=request,
            user_id=current_user.id,
            document_id=document.id,
        )
        await self.db.commit()


class RagSearchService(BaseDocumentService):
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: ChromaVectorStore,
    ) -> None:
        super().__init__(db, settings)
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    async def search(self, *, current_user: User, payload: RagSearchRequest) -> RagSearchResponse:
        query_embedding = self.embedding_provider.embed_query(payload.query)
        hits = self.vector_store.search(
            user_id=current_user.id,
            query_embedding=query_embedding,
            top_k=payload.top_k,
            document_id=payload.document_id,
        )
        chunks = await self.repository.get_chunks_by_ids(
            chunk_ids=[hit.chunk_id for hit in hits],
            user_id=current_user.id,
        )
        chunks_by_id = {chunk.id: chunk for chunk in chunks}

        results: list[RagSearchResult] = []
        for hit in hits:
            chunk = chunks_by_id.get(hit.chunk_id)
            if chunk is None:
                continue
            results.append(
                RagSearchResult(
                    document_id=chunk.document_id,
                    document_filename=chunk.document.filename,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    distance=hit.distance,
                    citation=self._citation(chunk.document.filename, chunk.chunk_index),
                    metadata=hit.metadata,
                )
            )

        return RagSearchResponse(query=payload.query, results=results)

    def _citation(self, filename: str, chunk_index: int) -> str:
        return f"{filename}#chunk-{chunk_index + 1}"


class RagQueryService(RagSearchService):
    async def query(self, *, current_user: User, payload: RagQueryRequest) -> RagQueryResponse:
        search_response = await self.search(current_user=current_user, payload=payload)
        citations = [
            RagCitation(
                document_id=result.document_id,
                document_filename=result.document_filename,
                chunk_id=result.chunk_id,
                chunk_index=result.chunk_index,
                citation=result.citation,
            )
            for result in search_response.results
        ]
        answer = self._build_grounded_answer(payload.query, search_response.results)
        return RagQueryResponse(
            question=payload.query,
            answer=answer,
            context=search_response.results,
            citations=citations,
        )

    def _build_grounded_answer(self, question: str, results: list[RagSearchResult]) -> str:
        if not results:
            return "I could not find relevant uploaded knowledge for that question."

        snippets = [
            f"[{index}] {result.content}"
            for index, result in enumerate(results[:3], start=1)
        ]
        return (
            "Grounded answer from uploaded knowledge:\n\n"
            + "\n\n".join(snippets)
            + "\n\nCitations: "
            + ", ".join(result.citation for result in results)
        )
