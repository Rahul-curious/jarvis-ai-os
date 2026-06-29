from __future__ import annotations

import hashlib
from dataclasses import dataclass


class ChunkingError(Exception):
    """Raised when chunking settings are invalid."""


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    content_hash: str
    char_count: int


class TextChunker:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size < 200:
            raise ChunkingError("chunk_size must be at least 200 characters")
        if chunk_overlap < 0:
            raise ChunkingError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ChunkingError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> list[TextChunk]:
        normalized = text.strip()
        if not normalized:
            return []

        chunks: list[TextChunk] = []
        start = 0
        while start < len(normalized):
            hard_end = min(start + self.chunk_size, len(normalized))
            end = self._find_natural_break(normalized, start, hard_end)
            content = normalized[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        content=content,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        char_count=len(content),
                    )
                )

            if end >= len(normalized):
                break
            start = max(end - self.chunk_overlap, start + 1)

        return chunks

    def _find_natural_break(self, text: str, start: int, hard_end: int) -> int:
        if hard_end >= len(text):
            return hard_end

        search_window = text[start:hard_end]
        for separator in ("\n\n", "\n", ". ", " "):
            index = search_window.rfind(separator)
            minimum_break = int(self.chunk_size * 0.55)
            if index >= minimum_break:
                return start + index + len(separator)

        return hard_end
