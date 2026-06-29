from __future__ import annotations

import pytest

from app.domains.documents.chunking import TextChunker
from app.domains.documents.parser import DocumentParser, DocumentParsingError


def test_document_parser_extracts_markdown_text() -> None:
    parsed = DocumentParser().parse(
        filename="notes.md",
        content=b"# JARVIS\n\nFastAPI powers the control plane.",
    )

    assert parsed.parser_name == "utf-8-text"
    assert "FastAPI powers" in parsed.text
    assert parsed.metadata["extension"] == ".md"


def test_document_parser_rejects_unsupported_extension() -> None:
    with pytest.raises(DocumentParsingError):
        DocumentParser().parse(filename="notes.docx", content=b"not supported")


def test_text_chunker_creates_overlapping_chunks() -> None:
    text = " ".join(f"token-{index}" for index in range(120))
    chunks = TextChunker(chunk_size=240, chunk_overlap=40).chunk(text)

    assert len(chunks) > 1
    assert chunks[0].index == 0
    assert chunks[1].index == 1
    assert chunks[0].content_hash != chunks[1].content_hash
    assert chunks[0].char_count <= 240
