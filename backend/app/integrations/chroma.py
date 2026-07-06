from __future__ import annotations

import chromadb

from app.core.config import get_settings


def create_chroma_http_client(*, host: str, port: int):
    """Create the HTTP client supported by the pinned Chroma 0.5.23 server."""
    return chromadb.HttpClient(host=host, port=port)


def get_chroma_client():
    settings = get_settings()
    return create_chroma_http_client(host=settings.chroma_host, port=settings.chroma_port)
