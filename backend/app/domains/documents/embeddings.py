from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol


class EmbeddingProviderError(Exception):
    """Raised when embeddings cannot be generated."""


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts."""

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query."""


class SentenceTransformerEmbeddingProvider:
    def __init__(self, *, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._model = None

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        embeddings = model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [self._coerce_vector(vector) for vector in embeddings]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingProviderError(
                "sentence-transformers is required for the default embedding provider"
            ) from exc

        self._model = SentenceTransformer(self.model_name)
        return self._model

    def _coerce_vector(self, vector) -> list[float]:
        values = [float(item) for item in vector.tolist()]
        if len(values) != self.dimensions:
            raise EmbeddingProviderError(
                f"Expected {self.dimensions} embedding dimensions, received {len(values)}"
            )
        return values


class HashEmbeddingProvider:
    """Deterministic lightweight provider for tests and local smoke checks."""

    def __init__(self, *, dimensions: int = 384) -> None:
        self.model_name = "hash/deterministic"
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = [token.strip().lower() for token in text.split() if token.strip()]
        if not tokens:
            tokens = [text.lower()]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]
