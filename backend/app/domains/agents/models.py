from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")

AGENT_DEFINITION_STATUS_VALUES = ("active", "disabled", "archived")
AGENT_RUN_STATUS_VALUES = (
    "requested",
    "validating",
    "queued",
    "running",
    "waiting_for_approval",
    "succeeded",
    "failed",
    "cancelled",
    "retriable",
)
AGENT_STEP_STATUS_VALUES = ("pending", "running", "succeeded", "failed", "cancelled", "skipped")


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_agent_definitions_status",
        ),
        Index("ix_agent_definitions_user_id", "user_id"),
        Index("ix_agent_definitions_agent_type", "agent_type"),
        Index("ix_agent_definitions_status", "status"),
        UniqueConstraint("user_id", "agent_key", name="uq_agent_definitions_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
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

    runs: Mapped[list[AgentRun]] = relationship(
        back_populates="definition",
        passive_deletes=True,
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('requested', 'validating', 'queued', 'running', 'waiting_for_approval', "
            "'succeeded', 'failed', 'cancelled', 'retriable')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_agent_runs_retry_count"),
        Index("ix_agent_runs_user_id", "user_id"),
        Index("ix_agent_runs_definition_id", "agent_definition_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="SET NULL"),
    )
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    input_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    output_text: Mapped[str | None] = mapped_column(Text)
    output_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    definition: Mapped[AgentDefinition | None] = relationship(back_populates="runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_index",
    )
    events: Mapped[list[AgentEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentEvent.sequence",
    )
    artifacts: Mapped[list[AgentArtifact]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentArtifact.created_at",
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        CheckConstraint("step_index >= 0", name="ck_agent_steps_step_index"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')",
            name="ck_agent_steps_status",
        ),
        UniqueConstraint("run_id", "step_index", name="uq_agent_steps_run_index"),
        Index("ix_agent_steps_run_id", "run_id"),
        Index("ix_agent_steps_user_id", "user_id"),
        Index("ix_agent_steps_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    output_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    run: Mapped[AgentRun] = relationship(back_populates="steps")
    events: Mapped[list[AgentEvent]] = relationship(
        back_populates="step",
        passive_deletes=True,
        order_by="AgentEvent.sequence",
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_agent_events_sequence"),
        UniqueConstraint("run_id", "sequence", name="uq_agent_events_run_sequence"),
        Index("ix_agent_events_run_id", "run_id"),
        Index("ix_agent_events_user_id", "user_id"),
        Index("ix_agent_events_event_type", "event_type"),
        Index("ix_agent_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_steps.id", ondelete="SET NULL"),
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AgentRun] = relationship(back_populates="events")
    step: Mapped[AgentStep | None] = relationship(back_populates="events")


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_agent_artifacts_size_bytes"),
        Index("ix_agent_artifacts_run_id", "run_id"),
        Index("ix_agent_artifacts_user_id", "user_id"),
        Index("ix_agent_artifacts_artifact_type", "artifact_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    storage_uri: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB_COMPAT,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AgentRun] = relationship(back_populates="artifacts")
