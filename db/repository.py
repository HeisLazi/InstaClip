"""Typed, creator-scoped repository layer (blueprint Phase 1).

The schema in `db/models.py` is the durable foundation; this module is how the
rest of the app reads and writes it without hand-rolling SQLAlchemy queries
everywhere. Every repository is scoped to a `creator_id` (tenant-ready) and never
leaks rows across creators.

Design:
- Repositories take a live `Session` (dependency-injected) so they compose inside
  one transaction and stay trivially testable against an in-memory engine.
- `session_scope()` is the convenience wrapper for app code: commit on success,
  rollback on error, always close. Tests pass their own session instead.

Usage (app code):

    from db.repository import session_scope, ClipCandidateRepo

    with session_scope() as s:
        repo = ClipCandidateRepo(s)
        cand = repo.create(stem="HNG_16", score=1.0, start=91.0, end=157.0)
        # commit happens on clean exit
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generic, Iterator, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.models import (
    Base,
    ClipCandidate,
    ClipVersion,
    Creator,
    Job,
    MemoryEntry,
    PostMetric,
    StreamFormat,
    StreamPlan,
    Vod,
    WorkflowEvent,
)

T = TypeVar("T", bound=Base)


@contextmanager
def session_scope(factory=SessionLocal) -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error, always close.

    `factory` is injectable so tests can bind to their own engine.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class BaseRepository(Generic[T]):
    """Generic CRUD scoped to a creator.

    Subclasses set `model`. If the model carries `creator_id` (TenantMixin), every
    query is auto-filtered and every create auto-stamped with `self.creator_id`.
    """

    model: Type[T]

    def __init__(self, session: Session, creator_id: str = DEFAULT_CREATOR_ID) -> None:
        self.session = session
        self.creator_id = creator_id

    # -- internals ---------------------------------------------------------
    @property
    def _tenant_scoped(self) -> bool:
        return hasattr(self.model, "creator_id")

    def _select(self):
        stmt = select(self.model)
        if self._tenant_scoped:
            stmt = stmt.where(self.model.creator_id == self.creator_id)
        return stmt

    # -- reads -------------------------------------------------------------
    def get(self, entity_id: str) -> Optional[T]:
        obj = self.session.get(self.model, entity_id)
        if obj is None:
            return None
        if self._tenant_scoped and getattr(obj, "creator_id") != self.creator_id:
            return None  # never leak another creator's row
        return obj

    def list(self, *, limit: Optional[int] = None, **filters: Any) -> list[T]:
        stmt = self._select()
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if self._tenant_scoped:
            stmt = stmt.where(self.model.creator_id == self.creator_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        return int(self.session.scalar(stmt) or 0)

    # -- writes ------------------------------------------------------------
    def create(self, **kwargs: Any) -> T:
        if self._tenant_scoped:
            kwargs.setdefault("creator_id", self.creator_id)
        obj = self.model(**kwargs)
        self.session.add(obj)
        self.session.flush()  # assign PK / defaults without committing
        return obj

    def add(self, obj: T) -> T:
        if self._tenant_scoped and not getattr(obj, "creator_id", None):
            obj.creator_id = self.creator_id
        self.session.add(obj)
        self.session.flush()
        return obj

    def update(self, obj: T, **kwargs: Any) -> T:
        for key, value in kwargs.items():
            setattr(obj, key, value)
        self.session.flush()
        return obj

    def delete(self, obj: T) -> None:
        self.session.delete(obj)
        self.session.flush()


class CreatorRepo(BaseRepository[Creator]):
    """Creators are the tenant root, so this repo is NOT creator-scoped itself."""

    model = Creator

    def get_by_slug(self, slug: str) -> Optional[Creator]:
        return self.session.scalar(select(Creator).where(Creator.slug == slug))

    def ensure(self, creator_id: str, slug: str, name: str = "") -> Creator:
        existing = self.session.get(Creator, creator_id)
        if existing is not None:
            return existing
        return self.create(id=creator_id, slug=slug, name=name)


class VodRepo(BaseRepository[Vod]):
    model = Vod

    def get_by_stem(self, stem: str) -> Optional[Vod]:
        return self.session.scalar(self._select().where(Vod.stem == stem))

    def upsert_by_stem(self, stem: str, **fields: Any) -> Vod:
        existing = self.get_by_stem(stem)
        if existing is not None:
            return self.update(existing, **fields)
        return self.create(stem=stem, **fields)


class ClipCandidateRepo(BaseRepository[ClipCandidate]):
    model = ClipCandidate

    def by_state(self, state: str, *, limit: Optional[int] = None) -> list[ClipCandidate]:
        return self.list(state=state, limit=limit)

    def for_vod(self, vod_id: str) -> list[ClipCandidate]:
        return self.list(vod_id=vod_id)

    def get_by_stem(self, stem: str) -> Optional[ClipCandidate]:
        return self.session.scalar(self._select().where(ClipCandidate.stem == stem))


class ClipVersionRepo(BaseRepository[ClipVersion]):
    model = ClipVersion

    def for_candidate(self, candidate_id: str) -> list[ClipVersion]:
        return self.list(candidate_id=candidate_id)


class WorkflowEventRepo(BaseRepository[WorkflowEvent]):
    """Append-only — there is no update/delete path by design."""

    model = WorkflowEvent

    def append(
        self,
        *,
        entity_type: str,
        entity_id: str,
        actor: str = "system",
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        reason: str = "",
        payload: Optional[dict] = None,
        model_version: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> WorkflowEvent:
        return self.create(
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            payload=payload,
            model_version=model_version,
            correlation_id=correlation_id,
        )

    def for_entity(self, entity_type: str, entity_id: str) -> list[WorkflowEvent]:
        stmt = (
            self._select()
            .where(WorkflowEvent.entity_type == entity_type)
            .where(WorkflowEvent.entity_id == entity_id)
            .order_by(WorkflowEvent.ts.asc())
        )
        return list(self.session.scalars(stmt).all())

    def update(self, *args: Any, **kwargs: Any):  # noqa: D401 - intentionally blocked
        raise NotImplementedError("WorkflowEvent is append-only")

    def delete(self, *args: Any, **kwargs: Any):  # noqa: D401 - intentionally blocked
        raise NotImplementedError("WorkflowEvent is append-only")


class JobRepo(BaseRepository[Job]):
    model = Job

    def by_idempotency(self, key: str) -> Optional[Job]:
        return self.session.scalar(self._select().where(Job.idempotency_key == key))

    def enqueue(self, kind: str, *, idempotency_key: Optional[str] = None, **fields: Any) -> Job:
        """Idempotent enqueue: returns the existing job if the key was seen."""
        if idempotency_key:
            existing = self.by_idempotency(idempotency_key)
            if existing is not None:
                return existing
        return self.create(kind=kind, status="queued", idempotency_key=idempotency_key, **fields)

    def queued(self, kind: Optional[str] = None) -> list[Job]:
        stmt = self._select().where(Job.status == "queued")
        if kind is not None:
            stmt = stmt.where(Job.kind == kind)
        stmt = stmt.order_by(Job.created_at.asc())
        return list(self.session.scalars(stmt).all())


class MemoryRepo(BaseRepository[MemoryEntry]):
    model = MemoryEntry

    def by_layer(self, layer: str, *, limit: Optional[int] = None) -> list[MemoryEntry]:
        return self.list(layer=layer, limit=limit)

    def get_by_layer_key(self, layer: str, key: str) -> Optional[MemoryEntry]:
        return self.session.scalar(
            self._select().where(MemoryEntry.layer == layer).where(MemoryEntry.key == key)
        )

    def upsert(self, layer: str, key: str, **fields: Any) -> MemoryEntry:
        existing = self.get_by_layer_key(layer, key)
        if existing is not None:
            return self.update(existing, **fields)
        return self.create(layer=layer, key=key, **fields)


class StreamPlanRepo(BaseRepository[StreamPlan]):
    model = StreamPlan

    def ordered(self, *, include_archived: bool = False) -> list[StreamPlan]:
        stmt = self._select()
        if not include_archived:
            stmt = stmt.where(StreamPlan.status != "archived")
        stmt = stmt.order_by(StreamPlan.scheduled_for.is_(None), StreamPlan.scheduled_for.asc(), StreamPlan.updated_at.desc())
        return list(self.session.scalars(stmt).all())


class StreamFormatRepo(BaseRepository[StreamFormat]):
    model = StreamFormat

    def ordered(self) -> list[StreamFormat]:
        stmt = self._select().order_by(StreamFormat.name.asc())
        return list(self.session.scalars(stmt).all())


class PostMetricRepo(BaseRepository[PostMetric]):
    model = PostMetric

    def get_by_post(self, platform: str, post_id: str) -> Optional[PostMetric]:
        return self.session.scalar(
            self._select().where(PostMetric.platform == platform)
            .where(PostMetric.post_id == post_id))

    def upsert(self, platform: str, post_id: str, **fields: Any) -> PostMetric:
        existing = self.get_by_post(platform, post_id)
        if existing is not None:
            return self.update(existing, **fields)
        return self.create(platform=platform, post_id=post_id, **fields)


__all__ = [
    "session_scope",
    "BaseRepository",
    "PostMetricRepo",
    "CreatorRepo",
    "VodRepo",
    "ClipCandidateRepo",
    "ClipVersionRepo",
    "WorkflowEventRepo",
    "JobRepo",
    "MemoryRepo",
    "StreamPlanRepo",
    "StreamFormatRepo",
]
