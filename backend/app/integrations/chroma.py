import chromadb

from app.core.config import get_settings


def get_chroma_client() -> chromadb.HttpClient:
    settings = get_settings()
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
