"""SQLAlchemy 2 models (Postgres in dev/prod; SQLite in unit tests). Migrations: Alembic.

PHI lives only in ``job_sources.document``, ``drafts.state``, ``review_actions.payload`` and
``approved_bundles.bundle`` (access-controlled database, not logs). ``jobs``, ``job_events`` and
``audit_events`` hold metadata only. The original filename is deliberately not stored (it is
often the patient's name).

``audit_events`` is append-only: a Postgres trigger (migration 0001) rejects UPDATE and DELETE.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute
        dict[str, Any]: JsonType,
        dt.datetime: DateTime(timezone=True),
        uuid.UUID: Uuid(),
    }


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    created_by: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(255))
    extractor: Mapped[str] = mapped_column(String(32))
    current_step: Mapped[str | None] = mapped_column(String(32), default=None)
    error_step: Mapped[str | None] = mapped_column(String(32), default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    """PHI-free by contract (fixed strings / ingest messages)."""
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Counts and fixed strings only."""
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class JobSource(Base):
    __tablename__ = "job_sources"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[dict[str, Any]]
    """``IngestedDocument`` JSON (PHI)."""


class Draft(Base):
    __tablename__ = "drafts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[dict[str, Any]]
    """``app.review.draft.DraftState`` JSON (PHI)."""
    pipeline_meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Extractor model, prompt version, grounding counts (no PHI)."""
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ReviewActionRecord(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    """The edit value / confirmation (PHI for edits)."""
    draft_version: Mapped[int] = mapped_column(Integer)
    """Draft version the action produced."""
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class ApprovedBundle(Base):
    __tablename__ = "approved_bundles"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    bundle: Mapped[dict[str, Any]]
    """The approved IPS Bundle (FHIR JSON, PHI)."""
    approved_by: Mapped[str] = mapped_column(String(255))
    reviewer_role: Mapped[str] = mapped_column(String(16))
    attester_mode: Mapped[str] = mapped_column(String(16))
    draft_version: Mapped[int] = mapped_column(Integer)
    validation: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    approved_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    """Append-only: who did what when. Never document content (paths and counts only)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None] = mapped_column(default=None, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
