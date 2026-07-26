from app.db.base import Base


def test_auth_metadata_contains_required_tables() -> None:
    assert {
        "users",
        "sessions",
        "audit_logs",
        "memory_items",
        "memory_events",
        "memory_references",
        "documents",
        "document_chunks",
        "agent_definitions",
        "agent_runs",
        "agent_steps",
        "agent_events",
        "agent_artifacts",
    }.issubset(Base.metadata.tables.keys())
