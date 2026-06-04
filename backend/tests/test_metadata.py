from app.db.base import Base


def test_auth_metadata_contains_required_tables() -> None:
    assert {"users", "sessions", "audit_logs"}.issubset(Base.metadata.tables.keys())
