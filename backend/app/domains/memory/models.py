from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MEMORY_TYPE_VALUES = (
    "short_term",
    "long_term",
    "user_preference",
    "project",
    "correction",
)


class MemoryItem(Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint(
            "memory_type IN "
            "('short_term', 'long_term', 'user_preference', 'project', 'correction')",
            name="ck_memory_items_memory_type",
        ),
        CheckConstraint(
            "importance_score >= 0 AND importance_score <= 1",
            name="ck_memory_items_importance_score",
        ),
        CheckConstraint(
            "reinforcement_count >= 0",
            name="ck_memory_items_reinforcement_count",
        ),
        Index("ix_memory_items_user_id", "user_id"),
        Index("ix_memory_items_memory_type", "memory_type"),
        Index("ix_memory_items_category", "category"),
        Index("ix_memory_items_importance_score", "importance_score"),
        Index("ix_memory_items_last_accessed_at", "last_accessed_at"),
        Index("ix_memory_items_active_lookup", "user_id", "memory_type", "category", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    reinforcement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[MemoryEvent]] = relationship(
        back_populates="memory_item",
        cascade="all, delete-orphan",
    )
    references: Mapped[list[MemoryReference]] = relationship(
        back_populates="memory_item",
        cascade="all, delete-orphan",
    )


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        Index("ix_memory_events_memory_item_id", "memory_item_id"),
        Index("ix_memory_events_user_id", "user_id"),
        Index("ix_memory_events_event_type", "event_type"),
        Index("ix_memory_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    score_after: Mapped[float | None] = mapped_column(Float)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    memory_item: Mapped[MemoryItem] = relationship(back_populates="events")


class MemoryReference(Base):
    __tablename__ = "memory_references"
    __table_args__ = (
        Index("ix_memory_references_memory_item_id", "memory_item_id"),
        Index("ix_memory_references_reference_type", "reference_type"),
        Index("ix_memory_references_reference_id", "reference_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(128))
    label: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    reference_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    memory_item: Mapped[MemoryItem] = relationship(back_populates="references")
