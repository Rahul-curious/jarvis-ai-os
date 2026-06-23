from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domains.memory.models import MemoryEvent, MemoryItem, MemoryReference

REGISTER_PAYLOAD = {
    "full_name": "Rahul Prakash",
    "email": "rahul.memory@example.com",
    "password": "correct-horse-battery",
}


def authenticate(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201


def create_memory(
    client: TestClient,
    *,
    content: str = "Rahul prefers implementation plans before code changes.",
    memory_type: str = "long_term",
    category: str = "workflow",
    importance_score: float = 0.7,
    source: str = "manual",
) -> dict:
    response = client.post(
        "/api/v1/memory",
        json={
            "memory_type": memory_type,
            "category": category,
            "content": content,
            "importance_score": importance_score,
            "source": source,
            "references": [
                {
                    "reference_type": "project",
                    "reference_id": "jarvis-ai-os",
                    "label": "JARVIS AI OS",
                    "metadata": {"phase": "4"},
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_memory_persists_item_reference_event_and_audit(client: TestClient) -> None:
    authenticate(client)
    body = create_memory(client)

    assert body["memory_type"] == "long_term"
    assert body["category"] == "workflow"
    assert body["reinforcement_count"] == 0
    assert body["memory_score"] == 0.49
    assert body["references"][0]["metadata"] == {"phase": "4"}

    async def inspect_db() -> tuple[int, int, int]:
        session_factory = client.app.state.test_session_factory
        async with session_factory() as session:
            item_count = await session.scalar(select(func.count(MemoryItem.id)))
            event_count = await session.scalar(select(func.count(MemoryEvent.id)))
            reference_count = await session.scalar(select(func.count(MemoryReference.id)))
            return int(item_count or 0), int(event_count or 0), int(reference_count or 0)

    assert asyncio.run(inspect_db()) == (1, 1, 1)


def test_memory_requires_authentication_and_validates_payload(client: TestClient) -> None:
    unauthenticated = client.post(
        "/api/v1/memory",
        json={
            "memory_type": "long_term",
            "category": "profile",
            "content": "Private context",
        },
    )
    assert unauthenticated.status_code == 401

    authenticate(client)
    invalid_type = client.post(
        "/api/v1/memory",
        json={
            "memory_type": "episodic",
            "category": "profile",
            "content": "Unsupported memory type",
        },
    )
    invalid_importance = client.post(
        "/api/v1/memory",
        json={
            "memory_type": "long_term",
            "category": "profile",
            "content": "Bad score",
            "importance_score": 2,
        },
    )
    past_expiration = client.post(
        "/api/v1/memory",
        json={
            "memory_type": "short_term",
            "category": "temporary",
            "content": "Expired context",
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )

    assert invalid_type.status_code == 422
    assert invalid_importance.status_code == 422
    assert past_expiration.status_code == 400


def test_short_term_memory_gets_default_expiration(client: TestClient) -> None:
    authenticate(client)
    memory = create_memory(
        client,
        memory_type="short_term",
        category="conversation",
        content="Temporary conversation context should expire.",
    )

    assert memory["expires_at"] is not None


def test_recall_increments_reinforcement_and_updates_last_accessed(client: TestClient) -> None:
    authenticate(client)
    memory = create_memory(client)

    first_recall = client.get(f"/api/v1/memory/{memory['id']}")
    second_recall = client.get(f"/api/v1/memory/{memory['id']}")

    assert first_recall.status_code == 200
    assert first_recall.json()["reinforcement_count"] == 1
    assert first_recall.json()["last_accessed_at"] is not None
    assert second_recall.json()["reinforcement_count"] == 2
    assert second_recall.json()["memory_score"] > memory["memory_score"]


def test_search_filters_by_keyword_category_type_and_ranks_importance(
    client: TestClient,
) -> None:
    authenticate(client)
    low = create_memory(
        client,
        content="Rahul likes Python examples with direct tests.",
        memory_type="user_preference",
        category="learning",
        importance_score=0.4,
    )
    high = create_memory(
        client,
        content="Rahul prefers Python architecture notes to be precise.",
        memory_type="user_preference",
        category="learning",
        importance_score=0.9,
    )
    create_memory(
        client,
        content="Project JARVIS uses FastAPI.",
        memory_type="project",
        category="jarvis",
        importance_score=1.0,
    )

    response = client.post(
        "/api/v1/memory/search",
        json={
            "keyword": "Python",
            "category": "learning",
            "memory_type": "user_preference",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [high["id"], low["id"]]


def test_update_and_delete_memory(client: TestClient) -> None:
    authenticate(client)
    memory = create_memory(client)

    update_response = client.put(
        f"/api/v1/memory/{memory['id']}",
        json={
            "category": "delivery",
            "content": "Rahul wants requirement-by-requirement evidence before completion.",
            "importance_score": 0.95,
        },
    )
    delete_response = client.delete(f"/api/v1/memory/{memory['id']}")
    recall_after_delete = client.get(f"/api/v1/memory/{memory['id']}")
    list_after_delete = client.get("/api/v1/memory")

    assert update_response.status_code == 200
    assert update_response.json()["category"] == "delivery"
    assert update_response.json()["importance_score"] == 0.95
    assert delete_response.status_code == 200
    assert recall_after_delete.status_code == 404
    assert list_after_delete.json()["total"] == 0


def test_reinforce_endpoint_increments_memory_score(client: TestClient) -> None:
    authenticate(client)
    memory = create_memory(client, importance_score=0.5)

    response = client.post(
        "/api/v1/memory/reinforce",
        json={"memory_id": memory["id"], "amount": 3, "reason": "Useful preference"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reinforcement_count"] == 3
    assert body["memory_score"] > memory["memory_score"]
