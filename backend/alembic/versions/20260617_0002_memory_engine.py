"""create memory engine tables

Revision ID: 20260617_0002
Revises: 20260604_0001
Create Date: 2026-06-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260617_0002"
down_revision: str | None = "20260604_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance_score", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("reinforcement_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=120), server_default="manual", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "memory_type IN "
            "('short_term', 'long_term', 'user_preference', 'project', 'correction')",
            name="ck_memory_items_memory_type",
        ),
        sa.CheckConstraint(
            "importance_score >= 0 AND importance_score <= 1",
            name="ck_memory_items_importance_score",
        ),
        sa.CheckConstraint(
            "reinforcement_count >= 0",
            name="ck_memory_items_reinforcement_count",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_items_user_id", "memory_items", ["user_id"])
    op.create_index("ix_memory_items_memory_type", "memory_items", ["memory_type"])
    op.create_index("ix_memory_items_category", "memory_items", ["category"])
    op.create_index("ix_memory_items_importance_score", "memory_items", ["importance_score"])
    op.create_index("ix_memory_items_last_accessed_at", "memory_items", ["last_accessed_at"])
    op.create_index(
        "ix_memory_items_active_lookup",
        "memory_items",
        ["user_id", "memory_type", "category", "deleted_at"],
    )

    op.create_table(
        "memory_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), server_default="success", nullable=False),
        sa.Column("score_after", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["memory_item_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_events_memory_item_id", "memory_events", ["memory_item_id"])
    op.create_index("ix_memory_events_user_id", "memory_events", ["user_id"])
    op.create_index("ix_memory_events_event_type", "memory_events", ["event_type"])
    op.create_index("ix_memory_events_created_at", "memory_events", ["created_at"])

    op.create_table(
        "memory_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["memory_item_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_references_memory_item_id",
        "memory_references",
        ["memory_item_id"],
    )
    op.create_index(
        "ix_memory_references_reference_type",
        "memory_references",
        ["reference_type"],
    )
    op.create_index(
        "ix_memory_references_reference_id",
        "memory_references",
        ["reference_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_references_reference_id", table_name="memory_references")
    op.drop_index("ix_memory_references_reference_type", table_name="memory_references")
    op.drop_index("ix_memory_references_memory_item_id", table_name="memory_references")
    op.drop_table("memory_references")

    op.drop_index("ix_memory_events_created_at", table_name="memory_events")
    op.drop_index("ix_memory_events_event_type", table_name="memory_events")
    op.drop_index("ix_memory_events_user_id", table_name="memory_events")
    op.drop_index("ix_memory_events_memory_item_id", table_name="memory_events")
    op.drop_table("memory_events")

    op.drop_index("ix_memory_items_active_lookup", table_name="memory_items")
    op.drop_index("ix_memory_items_last_accessed_at", table_name="memory_items")
    op.drop_index("ix_memory_items_importance_score", table_name="memory_items")
    op.drop_index("ix_memory_items_category", table_name="memory_items")
    op.drop_index("ix_memory_items_memory_type", table_name="memory_items")
    op.drop_index("ix_memory_items_user_id", table_name="memory_items")
    op.drop_table("memory_items")
