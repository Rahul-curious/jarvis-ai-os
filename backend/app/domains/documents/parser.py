from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


class DocumentParsingError(Exception):
    """Raised when a document cannot be parsed into text."""


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    parser_name: str
    metadata: dict[str, str | int]


class DocumentParser:
    supported_extensions = {".txt", ".md", ".markdown", ".pdf"}

    def parse(self, *, filename: str, content: bytes) -> ParsedDocument:
        extension = Path(filename).suffix.lower()
        if extension not in self.supported_extensions:
            raise DocumentParsingError("Only txt, md, and pdf documents are supported")

        if extension in {".txt", ".md", ".markdown"}:
            return self._parse_text(filename=filename, content=content)

        return self._parse_pdf(content)

    def _parse_text(self, *, filename: str, content: bytes) -> ParsedDocument:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParsingError("Text documents must be UTF-8 encoded") from exc

        return ParsedDocument(
            text=self._normalize_text(text),
            parser_name="utf-8-text",
            metadata={"extension": Path(filename).suffix.lower()},
        )

    def _parse_pdf(self, content: bytes) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentParsingError("PDF parsing requires the pypdf package") from exc

        try:
            reader = PdfReader(BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # pragma: no cover - pypdf raises several parser-specific errors.
            raise DocumentParsingError("Unable to parse PDF document") from exc

        text = self._normalize_text("\n\n".join(pages))
        return ParsedDocument(
            text=text,
            parser_name="pypdf",
            metadata={"page_count": len(pages), "extension": ".pdf"},
        )

    def _normalize_text(self, text: str) -> str:
        normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        normalized = "\n".join(normalized_lines).strip()
        if not normalized:
            raise DocumentParsingError("Document does not contain extractable text")
        return normalized
