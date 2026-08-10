"""Phase 3 Director Memory: the structured, creator-editable knowledge layer.

In-memory SQLite, no network. Covers upsert/recall/forget, layer validation,
the context_block digest, and deriving Clip DNA from review signals.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import CreatorRepo
from modules import director_memory


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


class DirectorMemoryTests(unittest.TestCase):
    def setUp(self):
        self.factory = _factory()

    def _remember(self, layer, key, value, **kw):
        return director_memory.remember(layer, key, value, factory=self.factory, **kw)

    def _recall(self, layer=None, **kw):
        return director_memory.recall(layer, factory=self.factory, **kw)

    def test_remember_and_recall(self):
        self._remember("brand", "voice", "dry, deadpan, no hype")
        entries = self._recall("brand")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "voice")
        self.assertEqual(entries[0]["value"], "dry, deadpan, no hype")
        self.assertEqual(entries[0]["source"], "manual")

    def test_upsert_by_layer_key(self):
        self._remember("brand", "voice", "v1")
        self._remember("brand", "voice", "v2", source="chat")
        entries = self._recall("brand")
        self.assertEqual(len(entries), 1)  # same layer+key updated, not duplicated
        self.assertEqual(entries[0]["value"], "v2")
        self.assertEqual(entries[0]["source"], "chat")

    def test_unknown_layer_rejected(self):
        with self.assertRaises(ValueError):
            self._remember("nonsense", "k", "v")

    def test_forget(self):
        e = self._remember("operational", "post_time", "evenings ET")
        self.assertTrue(director_memory.forget(e["id"], factory=self.factory))
        self.assertEqual(self._recall("operational"), [])
        # forgetting an unknown id is a no-op, not an error
        self.assertFalse(director_memory.forget("does-not-exist", factory=self.factory))

    def test_recall_all_layers(self):
        self._remember("brand", "voice", "x")
        self._remember("audience", "who", "y")
        self.assertEqual(len(self._recall()), 2)

    def test_context_block_orders_pinned_first(self):
        self._remember("operational", "z_note", "unpinned op")
        self._remember("brand", "voice", "pinned brand", pinned=True)
        block = director_memory.context_block(factory=self.factory)
        self.assertIn("Director memory", block)
        self.assertIn("[BRAND]", block)
        # pinned brand entry appears before the unpinned operational one
        self.assertLess(block.index("pinned brand"), block.index("unpinned op"))

    def test_context_block_empty_when_no_memory(self):
        self.assertEqual(director_memory.context_block(factory=self.factory), "")

    def test_derive_clip_dna_from_reviews(self):
        fake_reviews = [
            {"verdict": "keeper", "reasons": ["funny", "payoff"]},
            {"verdict": "keeper", "reasons": ["funny"]},
            {"verdict": "miss", "tags": ["bad trim good clip"]},  # boundary
            {"verdict": "miss", "reasons": ["off topic"]},        # genuine explained miss
            {"verdict": "miss"},                                   # NULL: no reason given
        ]

        def fake_classify(r):
            if r.get("verdict") == "keeper":
                return "positive"
            if "bad trim good clip" in (r.get("tags") or []):
                return "boundary"
            if not (r.get("tags") or r.get("reasons") or r.get("notes")):
                return "null"
            return "negative"

        import modules.clip_reviews as cr
        orig_list = cr.list_reviews
        orig_classify = cr.classify_review_signal
        cr.list_reviews = lambda *a, **k: fake_reviews
        cr.classify_review_signal = fake_classify
        try:
            result = director_memory.derive_clip_dna_from_reviews(factory=self.factory)
        finally:
            cr.list_reviews = orig_list
            cr.classify_review_signal = orig_classify

        # The bare "miss" is NULL (dupe/non-clip), not a true miss.
        self.assertEqual(result["null_junk"], 1)
        self.assertEqual(result["true_miss"], 1)
        dna = {e["key"]: e["value"] for e in self._recall("clip_dna")}
        self.assertIn("review_summary", dna)
        self.assertIn("boundaries", dna)
        self.assertIn("null_rejections", dna)
        self.assertIn("what_makes_a_keeper", dna)
        self.assertIn("1 true misses", dna["review_summary"])
        self.assertIn("1 null", dna["review_summary"])
        # core rules (boundaries, null) are pinned so they always reach the Director
        pinned = {e["key"] for e in self._recall("clip_dna") if e["pinned"]}
        self.assertIn("boundaries", pinned)
        self.assertIn("null_rejections", pinned)
        self.assertTrue(all(
            e["source"] == "derived_reviews" for e in self._recall("clip_dna")
        ))

    def test_derive_preserves_manual_override(self):
        self._remember(
            "clip_dna",
            "null_rejections",
            "My explicit override",
            source="manual",
            pinned=True,
        )

        import modules.clip_reviews as cr
        orig_list = cr.list_reviews
        cr.list_reviews = lambda *a, **k: [{"verdict": "miss"}]
        try:
            result = director_memory.derive_clip_dna_from_reviews(factory=self.factory)
        finally:
            cr.list_reviews = orig_list

        dna = {e["key"]: e for e in self._recall("clip_dna")}
        self.assertEqual(dna["null_rejections"]["value"], "My explicit override")
        self.assertEqual(dna["null_rejections"]["source"], "manual")
        self.assertEqual(result["preserved_manual"], 1)

    def test_boundary_direction_reads_notes(self):
        import modules.clip_reviews as cr
        reviews = [
            {"verdict": "miss", "tags": ["bad trim good clip"],
             "notes": "cut out right before the payoff, needs the ending"},
            {"verdict": "miss", "tags": ["bad trim good clip"],
             "notes": "this needs more context at the beginning / setup"},
            {"verdict": "miss", "tags": ["bad trim good clip"],
             "notes": "just needs to be a bit longer, too short"},
            {"verdict": "keeper", "notes": "great"},  # not a boundary
        ]

        def fake_classify(r):
            if r.get("verdict") == "keeper":
                return "positive"
            return "boundary"

        orig = cr.classify_review_signal
        cr.classify_review_signal = fake_classify
        try:
            d = director_memory._boundary_direction(reviews)
        finally:
            cr.classify_review_signal = orig
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["end"], 1)
        self.assertEqual(d["start"], 1)
        # note 2 ("needs more context") and note 3 ("longer/too short") both count.
        self.assertEqual(d["longer"], 2)

    def test_is_null_review(self):
        self.assertTrue(director_memory._is_null_review({"verdict": "miss"}))
        self.assertTrue(director_memory._is_null_review({"verdict": "bad", "notes": "  "}))
        self.assertFalse(director_memory._is_null_review({"verdict": "miss", "notes": "boring"}))
        self.assertFalse(director_memory._is_null_review({"verdict": "miss", "tags": ["x"]}))
        self.assertFalse(director_memory._is_null_review({"verdict": "keeper"}))


if __name__ == "__main__":
    unittest.main()
