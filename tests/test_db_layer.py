"""Phase 1 relational layer: repository CRUD + clip state machine.

Runs entirely against an in-memory SQLite engine, so it never touches the real
data/heislazi.db. No external services.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import (
    ClipCandidateRepo,
    ClipVersionRepo,
    CreatorRepo,
    JobRepo,
    VodRepo,
    WorkflowEventRepo,
)
from db.state_machine import (
    ClipState,
    InvalidTransition,
    can_transition,
    is_terminal,
    transition,
)


def _fresh_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = Session()
    CreatorRepo(session).ensure(DEFAULT_CREATOR_ID, DEFAULT_CREATOR_ID, "HeisLazi")
    session.commit()
    return session


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.session = _fresh_session()

    def tearDown(self):
        self.session.close()

    def test_create_autostamps_creator_id(self):
        cand = ClipCandidateRepo(self.session).create(stem="HNG_16", score=1.0)
        self.assertEqual(cand.creator_id, DEFAULT_CREATOR_ID)
        self.assertIsNotNone(cand.id)

    def test_get_is_creator_scoped(self):
        repo_a = ClipCandidateRepo(self.session, creator_id="heislazi")
        repo_b = ClipCandidateRepo(self.session, creator_id="someone_else")
        cand = repo_a.create(stem="mine")
        self.session.flush()
        # Same row id, different tenant -> must not leak.
        self.assertIsNotNone(repo_a.get(cand.id))
        self.assertIsNone(repo_b.get(cand.id))

    def test_vod_upsert_by_stem(self):
        repo = VodRepo(self.session)
        v1 = repo.upsert_by_stem("KOA", duration=100.0)
        v2 = repo.upsert_by_stem("KOA", duration=200.0)
        self.assertEqual(v1.id, v2.id)
        self.assertEqual(v2.duration, 200.0)
        self.assertEqual(repo.count(), 1)

    def test_candidate_by_state_and_for_vod(self):
        vod = VodRepo(self.session).create(stem="VOD1")
        repo = ClipCandidateRepo(self.session)
        repo.create(stem="a", state=ClipState.DETECTED, vod_id=vod.id)
        repo.create(stem="b", state=ClipState.CANDIDATE, vod_id=vod.id)
        self.session.flush()
        self.assertEqual(len(repo.by_state(ClipState.DETECTED)), 1)
        self.assertEqual(len(repo.for_vod(vod.id)), 2)

    def test_versions_link_to_candidate(self):
        cand = ClipCandidateRepo(self.session).create(stem="HNG_16")
        self.session.flush()
        vrepo = ClipVersionRepo(self.session)
        vrepo.create(candidate_id=cand.id, stem="HNG_16_edit", kind="edit", path="output/edited/x.mp4")
        self.session.flush()
        self.assertEqual(len(vrepo.for_candidate(cand.id)), 1)

    def test_job_enqueue_is_idempotent(self):
        repo = JobRepo(self.session)
        j1 = repo.enqueue("transcribe", idempotency_key="vod:KOA")
        j2 = repo.enqueue("transcribe", idempotency_key="vod:KOA")
        self.assertEqual(j1.id, j2.id)
        self.assertEqual(len(repo.queued()), 1)

    def test_workflow_event_repo_is_append_only(self):
        repo = WorkflowEventRepo(self.session)
        ev = repo.append(entity_type="clip_candidate", entity_id="x", to_state="CANDIDATE")
        with self.assertRaises(NotImplementedError):
            repo.update(ev, reason="nope")
        with self.assertRaises(NotImplementedError):
            repo.delete(ev)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.session = _fresh_session()
        self.cand = ClipCandidateRepo(self.session).create(stem="HNG_16", state=ClipState.DETECTED)
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def test_valid_transition_updates_state_and_logs_event(self):
        ev = transition(
            self.session, self.cand, ClipState.CANDIDATE, actor="judge", reason="score 1.0"
        )
        self.assertEqual(self.cand.state, ClipState.CANDIDATE)
        self.assertEqual(ev.from_state, ClipState.DETECTED)
        self.assertEqual(ev.to_state, ClipState.CANDIDATE)
        self.assertEqual(ev.actor, "judge")
        events = WorkflowEventRepo(self.session).for_entity("clip_candidate", self.cand.id)
        self.assertEqual(len(events), 1)

    def test_invalid_transition_raises_and_leaves_state(self):
        with self.assertRaises(InvalidTransition):
            transition(self.session, self.cand, ClipState.PUBLISHED)
        self.assertEqual(self.cand.state, ClipState.DETECTED)
        self.assertEqual(
            WorkflowEventRepo(self.session).for_entity("clip_candidate", self.cand.id), []
        )

    def test_unknown_target_state_raises(self):
        with self.assertRaises(InvalidTransition):
            transition(self.session, self.cand, "BANANA")

    def test_full_happy_path_to_learning_complete(self):
        path = [
            ClipState.CANDIDATE,
            ClipState.SENT_TO_DISCORD,
            ClipState.CLAIMED,
            ClipState.EDIT_REQUESTED,
            ClipState.RENDERING,
            ClipState.READY_FOR_REVIEW,
            ClipState.APPROVED,
            ClipState.SCHEDULED,
            ClipState.PUBLISHED,
            ClipState.MEASURED,
            ClipState.LEARNING_COMPLETE,
        ]
        for to_state in path:
            transition(self.session, self.cand, to_state, actor="test")
        self.assertEqual(self.cand.state, ClipState.LEARNING_COMPLETE)
        self.assertTrue(is_terminal(self.cand.state))
        events = WorkflowEventRepo(self.session).for_entity("clip_candidate", self.cand.id)
        self.assertEqual(len(events), len(path))
        # Events are returned in chronological order.
        self.assertEqual(events[0].to_state, ClipState.CANDIDATE)
        self.assertEqual(events[-1].to_state, ClipState.LEARNING_COMPLETE)

    def test_revision_loop_is_allowed(self):
        for to_state in [
            ClipState.CANDIDATE,
            ClipState.SENT_TO_DISCORD,
            ClipState.CLAIMED,
            ClipState.EDIT_REQUESTED,
            ClipState.RENDERING,
            ClipState.READY_FOR_REVIEW,
            ClipState.REVISION_REQUESTED,
            ClipState.EDIT_REQUESTED,
        ]:
            transition(self.session, self.cand, to_state, actor="test")
        self.assertEqual(self.cand.state, ClipState.EDIT_REQUESTED)

    def test_terminal_states_have_no_exits(self):
        self.assertFalse(can_transition(ClipState.LEARNING_COMPLETE, ClipState.MEASURED))
        self.assertFalse(can_transition(ClipState.REJECTED, ClipState.CANDIDATE))


if __name__ == "__main__":
    unittest.main()
