"""Core relational entities (blueprint Phase 1 starter subset).

Covers what Phase 2 (Discord Clip Room) needs first: the clip pipeline
(vods -> candidates -> versions), the append-only workflow/audit event log, and
persistent jobs. The rest of the blueprint's entity list is layered on later.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TenantMixin, TimestampMixin, new_id


class Creator(Base, TimestampMixin):
    __tablename__ = "creators"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")


class Vod(Base, TenantMixin, TimestampMixin):
    __tablename__ = "vods"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    stem: Mapped[str] = mapped_column(String(300), index=True)
    path: Mapped[str] = mapped_column(Text, default="")
    transcribed: Mapped[bool] = mapped_column(default=False)
    duration: Mapped[float] = mapped_column(default=0.0)
    candidates: Mapped[list["ClipCandidate"]] = relationship(back_populates="vod")


class ClipCandidate(Base, TenantMixin, TimestampMixin):
    """A detected moment. `state` drives the Phase 2 clip state machine."""
    __tablename__ = "clip_candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    vod_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vods.id"), nullable=True, index=True)
    stem: Mapped[str] = mapped_column(String(300), index=True)
    state: Mapped[str] = mapped_column(String(40), default="DETECTED", index=True)
    score: Mapped[float] = mapped_column(default=0.0)
    start: Mapped[float] = mapped_column(default=0.0)
    end: Mapped[float] = mapped_column(default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    hazards: Mapped[list] = mapped_column(JSON, default=list)
    # Phase 2 Discord Clip Room coordination state.
    claimed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    discord_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    discord_thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    vod: Mapped[Optional[Vod]] = relationship(back_populates="candidates")
    versions: Mapped[list["ClipVersion"]] = relationship(back_populates="candidate")


class ClipVersion(Base, TenantMixin, TimestampMixin):
    """A rendered output (raw cut, edit, compilation) of a candidate."""
    __tablename__ = "clip_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    candidate_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clip_candidates.id"), nullable=True, index=True)
    stem: Mapped[str] = mapped_column(String(300), index=True)
    bucket: Mapped[str] = mapped_column(String(40), default="edited")
    path: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="edit")  # raw | edit | compilation
    edit_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    candidate: Mapped[Optional[ClipCandidate]] = relationship(back_populates="versions")


class WorkflowEvent(Base, TenantMixin):
    """Append-only audit log. Every state transition / model decision / approval
    records actor, from/to state, reason, payload, correlation id, and time."""
    __tablename__ = "workflow_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)  # clip_candidate | clip_version | job
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    from_state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    to_state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    ts: Mapped[float] = mapped_column(default=__import__("time").time, index=True)


class Job(Base, TenantMixin, TimestampMixin):
    """Persistent job with retry, idempotency, and progress — outlives restarts."""
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|done|failed|cancelled
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, unique=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # self-describing input for recovery/outbox
    progress: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# Cloud/owner-only models are registered here for source compatibility but their
# backing tables are intentionally not created by the public-edition migrations.
# The repo classes remain so existing code that imports them does not break.

class MemoryEntry(Base, TenantMixin, TimestampMixin):
    """A durable fact the Content Director reads (owner-only cloud extension)."""
    __tablename__ = "memory_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    layer: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(160), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    confidence: Mapped[float] = mapped_column(default=1.0)
    pinned: Mapped[bool] = mapped_column(default=False)


class PostMetric(Base, TenantMixin, TimestampMixin):
    """Per-post social analytics (owner-only cloud extension)."""
    __tablename__ = "post_metrics"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(24), index=True)
    post_id: Mapped[str] = mapped_column(String(128), index=True)
    post_url: Mapped[str] = mapped_column(Text, default="")
    account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    clip_stem: Mapped[Optional[str]] = mapped_column(String(300), nullable=True, index=True)
    format_name: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    posted_at: Mapped[Optional[float]] = mapped_column(nullable=True)
    synced_at: Mapped[float] = mapped_column(default=0.0)
    views: Mapped[int] = mapped_column(default=0)
    likes: Mapped[int] = mapped_column(default=0)
    comments: Mapped[int] = mapped_column(default=0)
    shares: Mapped[int] = mapped_column(default=0)
    saves: Mapped[int] = mapped_column(default=0)
    reach: Mapped[int] = mapped_column(default=0)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class StreamPlan(Base, TenantMixin, TimestampMixin):
    """Stream production brief (owner-only cloud extension)."""
    __tablename__ = "stream_plans"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240), default="Untitled stream")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    scheduled_for: Mapped[Optional[float]] = mapped_column(nullable=True, index=True)
    format_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    brief: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class StreamFormat(Base, TenantMixin, TimestampMixin):
    """Reusable stream format (owner-only cloud extension)."""
    __tablename__ = "stream_formats"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), index=True)
    category: Mapped[str] = mapped_column(String(60), default="community", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


Index("ix_workflow_entity", WorkflowEvent.entity_type, WorkflowEvent.entity_id)
