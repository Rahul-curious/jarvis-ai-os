from __future__ import annotations

import uuid

from app.domains.memory.models import MemoryItem
from app.domains.memory.services import calculate_memory_score


def test_calculate_memory_score_combines_importance_and_reinforcement() -> None:
    memory = MemoryItem(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        memory_type="long_term",
        category="profile",
        content="Rahul prefers concise implementation summaries.",
        importance_score=0.8,
        reinforcement_count=4,
        source="manual",
    )

    assert calculate_memory_score(memory) == 0.68


def test_calculate_memory_score_caps_at_one() -> None:
    memory = MemoryItem(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        memory_type="correction",
        category="feedback",
        content="Always verify repository paths before editing.",
        importance_score=1.0,
        reinforcement_count=25,
        source="user_feedback",
    )

    assert calculate_memory_score(memory) == 1.0
