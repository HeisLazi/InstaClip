"""Phase 2 Discord Clip Room: the full clip lifecycle, edit validation, audit.

In-memory SQLite, no network (a recording gateway stands in for Discord).
"""

import unittest

from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base, ClipCandidate
from db.repository import ClipCandidateRepo, CreatorRepo, VodRepo
from db.state_machine import ClipState, InvalidTransition
from modules import clip_room
from modules.clip_room import (
    ClipRoom,
    EditValidationError,
    build_candidate_card,
    validate_edit_request,
)


class RecordingGateway:
    """Captures what would have been sent to Discord."""

    def __init__(self):
        self.cards = []
        self.results = []
        self.counter = 0

    def post_candidate_card(self, card):
        self.counter += 1
        mid = f"msg-{self.counter}"
        self.cards.append(card)
        return {"message_id": mid, "thread_id": f"thr-{self.counter}"}

    def post_render_result(self, thread_id, version):
        self.results.append((thread_id, version))

    def notify(self, message):
        pass


class _BoomOnceGateway(RecordingGateway):
    """Raises on the first post attempt, succeeds after — to exercise the outbox
    release-and-retry path."""

    def __init__(self):
        super().__init__()
        self.attempts = 0

    def post_candidate_card(self, card):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("discord post failed")
        return super().post_candidate_card(card)


def _factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    CreatorRepo(s).ensure(DEFAULT_CREATOR_ID, DEFAULT_CREATOR_ID, "HeisLazi")
    s.commit()
    s.close()
    return Session


class EditValidationTests(unittest.TestCase):
    def test_accepts_a_clean_request(self):
        spec = validate_edit_request({
            "trim": {"start": 2.0, "end": 12.0},
            "layout": "reaction",
            "audio_normalize": True,
            "sound_fx": [{"name": "boom", "at": 1.5, "gain": 0.9}],
        })
        self.assertEqual(spec["trim"], {"start": 2.0, "end": 12.0})
        self.assertEqual(spec["layout"], "reaction")
        self.assertTrue(spec["audio_normalize"])

    def test_rejects_unknown_fields(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"ffmpeg_args": "-vf scale=2:2"})

    def test_rejects_bad_trim_and_layout_and_boost(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"trim": {"start": 10, "end": 5}})
        with self.assertRaises(EditValidationError):
            validate_edit_request({"layout": "hologram"})
        with self.assertRaises(EditValidationError):
            validate_edit_request({"audio_boost_db": 999})

    def test_rejects_output_stem_with_path(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"output_stem": "../../etc/passwd"})

    def test_rejects_output_stem_with_windows_invalid_chars(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"output_stem": "my:clip*?"})

    def test_rejects_non_bool_audio_normalize(self):
        # bool("false") is True — must be rejected, not silently coerced.
        with self.assertRaises(EditValidationError):
            validate_edit_request({"audio_normalize": "false"})

    def test_rejects_negative_box_size(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"crop_box": [0, 0, -5, 10]})

    def test_rejects_unbounded_fx_gain(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({"sound_fx": [{"name": "boom", "at": 0.0, "gain": 999}]})

    def test_rejects_empty_request(self):
        with self.assertRaises(EditValidationError):
            validate_edit_request({})


class ClipRoomLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.factory = _factory()
        self.gw = RecordingGateway()
        self.room = ClipRoom(session_factory=self.factory, gateway=self.gw)
        with self.factory() as s:
            vod = VodRepo(s).create(stem="HE NOT GAY")
            cand = ClipCandidateRepo(s).create(
                stem="HNG_16", state=ClipState.DETECTED, score=1.0,
                start=91.0, end=157.0, reason="three thick bad jitas", vod_id=vod.id,
            )
            s.commit()
            self.cid = cand.id

    def tearDown(self):
        pass

    def _state(self):
        with self.factory() as s:
            return ClipCandidateRepo(s).get(self.cid).state

    def test_card_has_review_fields(self):
        card = self.room.prepare_card(self.cid)
        self.assertEqual(card["title"], "three thick bad jitas")
        self.assertEqual(card["duration"], 66.0)
        self.assertEqual(card["score"], 1.0)

    def test_full_happy_path_detected_to_approved(self):
        self.room.promote(self.cid, actor="director")
        sent = self.room.send_to_discord(self.cid)
        self.assertEqual(sent["state"], ClipState.SENT_TO_DISCORD)
        self.assertEqual(sent["discord_message_id"], "msg-1")
        self.assertEqual(len(self.gw.cards), 1)

        claimed = self.room.claim(self.cid, actor="editor_dave")
        self.assertEqual(claimed["claimed_by"], "editor_dave")

        self.room.request_edit(self.cid, {"trim": {"start": 90.0, "end": 158.0}}, actor="editor_dave")
        self.room.start_render(self.cid)
        ready = self.room.complete_render(self.cid, path="output/edited/HNG_16.mp4", kind="edit")
        self.assertEqual(ready["state"], ClipState.READY_FOR_REVIEW)
        # The render result was pushed back to the candidate's thread.
        self.assertEqual(self.gw.results[0][0], "thr-1")

        approved = self.room.approve(self.cid, actor="lazi")
        self.assertEqual(approved["state"], ClipState.APPROVED)

        # A ClipVersion was recorded and linked.
        with self.factory() as s:
            versions = ClipCandidateRepo(s).get(self.cid).versions
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].path, "output/edited/HNG_16.mp4")

    def test_extend_before_adjusts_window_and_moves_to_edit_requested(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        out = self.room.extend_before(self.cid, 5.0, actor="dave")
        self.assertEqual(out["start"], 86.0)  # 91 - 5
        self.assertEqual(out["state"], ClipState.EDIT_REQUESTED)

    def test_reject_from_review(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        self.room.request_raw(self.cid, actor="dave")
        self.room.start_render(self.cid)
        self.room.complete_render(self.cid, path="x.mp4", kind="raw")
        rejected = self.room.reject(self.cid, actor="lazi", reason="not funny enough")
        self.assertEqual(rejected["state"], ClipState.REJECTED)

    def test_invalid_action_for_state_is_blocked(self):
        # Cannot approve a freshly detected candidate.
        with self.assertRaises(InvalidTransition):
            self.room.approve(self.cid, actor="lazi")
        self.assertEqual(self._state(), ClipState.DETECTED)

    def test_audit_trail_records_every_actor_and_transition(self):
        self.room.promote(self.cid, actor="director")
        self.room.send_to_discord(self.cid, actor="director")
        self.room.claim(self.cid, actor="dave")
        trail = self.room.audit_trail(self.cid)
        self.assertEqual([e["to"] for e in trail],
                         [ClipState.CANDIDATE, ClipState.SENT_TO_DISCORD, ClipState.CLAIMED])
        self.assertEqual(trail[-1]["actor"], "dave")

    def test_by_state_query(self):
        self.room.promote(self.cid)
        sent = self.room.by_state(ClipState.CANDIDATE)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["id"], self.cid)

    def test_bad_edit_request_does_not_change_state(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        with self.assertRaises(EditValidationError):
            self.room.request_edit(self.cid, {"ffmpeg_args": "rm -rf"}, actor="dave")
        self.assertEqual(self._state(), ClipState.CLAIMED)  # unchanged

    def test_send_to_discord_is_idempotent(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        again = self.room.send_to_discord(self.cid)  # retry / double-click
        self.assertEqual(len(self.gw.cards), 1)  # card posted only once
        self.assertEqual(again["state"], ClipState.SENT_TO_DISCORD)

    def test_reserved_in_flight_send_is_not_reposted(self):
        # Simulate a crash / overlap: the row is reserved (SENT_TO_DISCORD) but no
        # message id was recorded yet. A concurrent send must NOT post again.
        self.room.promote(self.cid)
        with self.factory() as s:
            s.execute(
                update(ClipCandidate)
                .where(ClipCandidate.id == self.cid)
                .values(state=ClipState.SENT_TO_DISCORD, discord_message_id=None)
            )
            s.commit()
        out = self.room.send_to_discord(self.cid)
        self.assertEqual(len(self.gw.cards), 0)  # nothing posted
        self.assertEqual(out["state"], ClipState.SENT_TO_DISCORD)

    def test_failed_post_releases_reservation_for_retry(self):
        boom = _BoomOnceGateway()
        room = ClipRoom(session_factory=self.factory, gateway=boom)
        room.promote(self.cid)
        with self.assertRaises(RuntimeError):
            room.send_to_discord(self.cid)          # network throws
        self.assertEqual(self._state(), ClipState.CANDIDATE)  # released for retry
        sent = room.send_to_discord(self.cid)       # retry succeeds
        self.assertEqual(sent["state"], ClipState.SENT_TO_DISCORD)
        self.assertEqual(sent["discord_message_id"], "msg-1")
        self.assertEqual(len(boom.cards), 1)        # posted exactly once overall

    def test_recover_stuck_sends_resets_unposted_reservations(self):
        self.room.promote(self.cid)
        with self.factory() as s:
            s.execute(
                update(ClipCandidate)
                .where(ClipCandidate.id == self.cid)
                .values(state=ClipState.SENT_TO_DISCORD, discord_message_id=None)
            )
            s.commit()
        self.assertEqual(self.room.recover_stuck_sends(), 1)
        self.assertEqual(self._state(), ClipState.CANDIDATE)
        # A fully-sent card (message id present) is left alone.
        self.room.send_to_discord(self.cid)
        self.assertEqual(self.room.recover_stuck_sends(), 0)
        self.assertEqual(self._state(), ClipState.SENT_TO_DISCORD)

    def test_double_claim_is_blocked(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        with self.assertRaises(InvalidTransition):
            self.room.claim(self.cid, actor="eve")  # loses the race
        with self.factory() as s:
            self.assertEqual(ClipCandidateRepo(s).get(self.cid).claimed_by, "dave")

    def test_extend_rejects_non_positive_seconds(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        with self.assertRaises(EditValidationError):
            self.room.extend_after(self.cid, 0, actor="dave")
        with self.assertRaises(EditValidationError):
            self.room.extend_before(self.cid, -5, actor="dave")

    def test_complete_render_rejects_bad_kind(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        self.room.request_raw(self.cid, actor="dave")
        self.room.start_render(self.cid)
        with self.assertRaises(EditValidationError):
            self.room.complete_render(self.cid, path="x.mp4", kind="malware", bucket="edited")


class ClipRoomLearningTests(unittest.TestCase):
    """Clip-room outcomes (approve/revision/reject) become review signals that
    feed the learning loop, classified correctly (boundary != negative)."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from modules import clip_reviews

        self.factory = _factory()
        self.room = ClipRoom(session_factory=self.factory, gateway=RecordingGateway())
        self.tmp = tempfile.TemporaryDirectory()
        self._reviews_patch = patch.object(
            clip_reviews.paths, "CLIP_REVIEWS_FILE", Path(self.tmp.name) / "clip_reviews.json"
        )
        self._reviews_patch.start()
        with self.factory() as s:
            cand = ClipCandidateRepo(s).create(
                stem="HNG_16", state=ClipState.DETECTED, start=10.0, end=40.0, reason="bit"
            )
            s.commit()
            self.cid = cand.id
        # Drive to READY_FOR_REVIEW with a rendered version file.
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        self.room.request_raw(self.cid, actor="dave")
        self.room.start_render(self.cid)
        self.room.complete_render(self.cid, path="output/clips/HNG_16_cut.mp4", kind="raw", bucket="output")

    def tearDown(self):
        self._reviews_patch.stop()
        self.tmp.cleanup()

    def test_approve_records_positive_signal(self):
        from modules.clip_reviews import classify_review_signal, get_review

        self.room.approve(self.cid, actor="lazi")
        r = get_review("HNG_16_cut")
        self.assertIsNotNone(r)
        self.assertEqual(r["verdict"], "keeper")
        self.assertEqual(classify_review_signal(r), "positive")

    def test_revision_records_boundary_not_negative(self):
        from modules.clip_reviews import classify_review_signal, get_review

        self.room.request_revision(self.cid, "cut off right before the punchline", actor="lazi")
        r = get_review("HNG_16_cut")
        self.assertIn("bad trim good clip", r["tags"])
        self.assertEqual(classify_review_signal(r), "boundary")  # NOT negative training evidence

    def test_reject_true_miss_is_negative(self):
        from modules.clip_reviews import classify_review_signal, get_review

        self.room.reject(self.cid, actor="lazi", reason="not funny")
        r = get_review("HNG_16_cut")
        self.assertEqual(r["verdict"], "miss")
        self.assertEqual(classify_review_signal(r), "negative")

    def test_reject_with_boundary_reason_is_not_negative(self):
        from modules.clip_reviews import classify_review_signal, get_review

        self.room.reject(self.cid, actor="lazi", reason="good clip but cut out before the good part")
        r = get_review("HNG_16_cut")
        # The classifier reads the reason — a boundary complaint isn't a true negative.
        self.assertEqual(classify_review_signal(r), "boundary")


if __name__ == "__main__":
    unittest.main()
