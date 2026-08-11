"""Phase 3 — the Director reads memory: memory-aware candidate ranking.

Covers the NULL/repeat de-prioritisation (Lazarus's rule applied at selection),
the rationale on every adjustment, the score-only-nudged guarantee, and that the
rule is gated on memory holding it.
"""

import unittest

from modules import director


class _Cand:
    """Minimal stand-in for a ClipCandidate ORM row."""
    def __init__(self, cid, score, reason, state="DETECTED"):
        self.id = cid
        self.score = score
        self.reason = reason
        self.state = state


RULES = {"null_rejections": "bad with no reason is null", "boundaries": "..."}


class DirectorEvaluateTests(unittest.TestCase):
    def test_repetitive_filler_is_penalised(self):
        c = _Cand("a", 0.7, "catch on, catch on, catch on, catch on, catch on, catch on")
        j = director.evaluate_candidate(c, memory_rules=RULES)
        self.assertLess(j.adjustment, 0)
        self.assertTrue(j.is_null_like)
        self.assertTrue(any("null-like" in n for n in j.notes))

    def test_back_to_back_stutter_is_penalised(self):
        c = _Cand("a", 0.6, "swear swear swear swear i mean it")
        j = director.evaluate_candidate(c, memory_rules=RULES)
        self.assertLess(j.adjustment, 0)

    def test_clean_moment_is_untouched(self):
        c = _Cand("a", 0.92, "bet reveal")  # short but high-signal descriptor
        j = director.evaluate_candidate(c, memory_rules=RULES)
        self.assertEqual(j.adjustment, 0.0)
        self.assertEqual(j.adjusted_score, 0.92)

    def test_penalty_is_capped(self):
        c = _Cand("a", 0.5, "a a a a a a a a a a a a a a a a")
        j = director.evaluate_candidate(c, memory_rules=RULES)
        self.assertGreaterEqual(j.adjustment, -director.MAX_PENALTY - 1e-9)

    def test_rule_gated_on_memory(self):
        # If the creator's memory does NOT hold the null rule, the Director does
        # not apply the penalty (acts on what it knows, not a hardcoded opinion).
        c = _Cand("a", 0.7, "catch on, catch on, catch on, catch on, catch on, catch on")
        j = director.evaluate_candidate(c, memory_rules={"boundaries": "..."})
        self.assertEqual(j.adjustment, 0.0)

    def test_accepts_plain_dict(self):
        j = director.evaluate_candidate(
            {"score": 0.7, "reason": "swear swear swear swear"}, memory_rules=RULES
        )
        self.assertLess(j.adjustment, 0)


class DirectorRankTests(unittest.TestCase):
    def test_null_like_sinks_below_real_moment(self):
        good = _Cand("good", 0.70, "hello? yo, sham — bet reveal moment")
        repeat = _Cand("repeat", 0.72, "anyways anyways anyways anyways peloni exactly")
        ranked = director.rank_candidates([repeat, good], memory_rules=RULES)
        # repeat has the higher RAW score but should rank below the real moment
        order = [c.id for c, _ in ranked]
        self.assertEqual(order[0], "good")
        self.assertEqual(order[1], "repeat")

    def test_returns_judgement_per_candidate(self):
        ranked = director.rank_candidates(
            [_Cand("a", 0.5, "clean line here that is fine")], memory_rules=RULES
        )
        self.assertEqual(len(ranked), 1)
        cand, judgement = ranked[0]
        self.assertIsInstance(judgement, director.Judgement)
        self.assertIn("adjusted_score", judgement.as_dict())


if __name__ == "__main__":
    unittest.main()
