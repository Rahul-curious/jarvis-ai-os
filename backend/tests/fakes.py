from __future__ import annotations

import math
from typing import Any


class InMemoryChromaClient:
    def __init__(self) -> None:
        self._collections: dict[str, InMemoryChromaCollection] = {}

    def get_or_create_collection(self, *, name: str) -> InMemoryChromaCollection:
        if name not in self._collections:
            self._collections[name] = InMemoryChromaCollection()
        return self._collections[name]


class InMemoryChromaCollection:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def upsert(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        for index, vector_id in enumerate(ids):
            self._records[vector_id] = {
                "embedding": embeddings[index],
                "document": documents[index],
                "metadata": metadatas[index],
            }

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, Any],
        include: list[str],
    ) -> dict[str, list[list[Any]]]:
        del include
        query_embedding = query_embeddings[0]
        matches = [
            (vector_id, record)
            for vector_id, record in self._records.items()
            if self._matches_where(record["metadata"], where)
        ]
        ranked = sorted(
            matches,
            key=lambda item: self._distance(query_embedding, item[1]["embedding"]),
        )[:n_results]
        return {
            "ids": [[vector_id for vector_id, _record in ranked]],
            "metadatas": [[record["metadata"] for _vector_id, record in ranked]],
            "distances": [
                [
                    self._distance(query_embedding, record["embedding"])
                    for _vector_id, record in ranked
                ]
            ],
        }

    def delete(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        if ids is not None:
            for vector_id in ids:
                self._records.pop(vector_id, None)
            return

        if where is None:
            return

        for vector_id, record in list(self._records.items()):
            if self._matches_where(record["metadata"], where):
                self._records.pop(vector_id, None)

    def count(self) -> int:
        return len(self._records)

    def _matches_where(self, metadata: dict[str, Any], where: dict[str, Any]) -> bool:
        if "$and" in where:
            return all(self._matches_where(metadata, clause) for clause in where["$and"])
        return all(str(metadata.get(key)) == str(value) for key, value in where.items())

    def _distance(self, left: list[float], right: list[float]) -> float:
        return math.sqrt(
            sum(
                (left_value - right_value) ** 2
                for left_value, right_value in zip(left, right, strict=True)
            )
        )
