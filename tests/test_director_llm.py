"""Phase 3 — LLM taste judge on the promoted top-N.

No network: the LLM call is injected. Covers verdict parsing/normalization, the
non-fatal contract, recording verdicts as workflow events + reading them back, and
that the pipeline default never calls out.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import ClipCandidateRepo, CreatorRepo
from db.state_machine import ClipState
from modules import director


def _factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    CreatorRepo(s).ensure(DEFAULT_CREATOR_ID, DEFAULT_CREATOR_ID, "HeisLazi")
    s.commit()
    s.close()
    return Session


class LlmJudgeParsingTests(unittest.TestCase):
    def test_parses_and_normalizes_json(self):
        v = director.llm_judge_candidate(
            {"score": 0.9, "reason": "bet reveal payoff"},
            client_call=lambda sysp, usr: '{"fit": 0.82, "verdict": "keep", "why": "clean payoff"}',
        )
        self.assertEqual(v["verdict"], "keep")
        self.assertEqual(v["fit"], 0.82)
        self.assertEqual(v["why"], "clean payoff")

    def test_derives_verdict_from_fit_when_missing(self):
        v = director.llm_judge_candidate(
            {"reason": "x"}, client_call=lambda s, u: '{"fit": 0.2}',
        )
        self.assertEqual(v["verdict"], "skip")

    def test_clamps_out_of_range_fit(self):
        v = director.llm_judge_candidate(
            {"reason": "x"}, client_call=lambda s, u: '{"fit": 5, "verdict": "keep"}',
        )
        self.assertEqual(v["fit"], 1.0)

    def test_none_when_no_llm(self):
        self.assertIsNone(director.llm_judge_candidate({"reason": "x"}, client_call=lambda s, u: None))

    def test_non_fatal_on_bad_json(self):
        self.assertIsNone(director.llm_judge_candidate({"reason": "x"}, client_call=lambda s, u: "not json"))

    def test_non_fatal_on_raising_client(self):
        def boom(s, u):
            raise RuntimeError("429")
        self.assertIsNone(director.llm_judge_candidate({"reason": "x"}, client_call=boom))

    def test_memory_block_is_passed_into_prompt(self):
        seen = {}
        def capture(system, user):
            seen["system"] = system
            return '{"fit": 0.5, "verdict": "maybe", "why": "ok"}'
        director.llm_judge_candidate({"reason": "x"}, memory_block="LOVES chaos energy",
                                     client_call=capture)
        self.assertIn("LOVES chaos energy", seen["system"])


class LlmJudgeRecordTests(unittest.TestCase):
    def setUp(self):
        self.factory = _factory()
        with self.factory() as s:
            c = ClipCandidateRepo(s).create(stem="A_1", state=ClipState.CANDIDATE,
                                            score=0.8, start=10.0, end=40.0, reason="funny bit")
            s.commit()
            self.cid = c.id

    def test_records_and_reads_back_verdict(self):
        n = director.judge_and_record(
            [self.cid], factory=self.factory,
            client_call=lambda s, u: '{"fit": 0.7, "verdict": "keep", "why": "matches taste"}',
        )
        self.assertEqual(n, 1)
        v = director.latest_verdict(self.cid, factory=self.factory)
        self.assertEqual(v["verdict"], "keep")
        self.assertEqual(v["why"], "matches taste")

    def test_no_verdict_recorded_when_llm_unavailable(self):
        n = director.judge_and_record([self.cid], factory=self.factory, client_call=lambda s, u: None)
        self.assertEqual(n, 0)
        self.assertIsNone(director.latest_verdict(self.cid, factory=self.factory))

    def test_missing_candidate_is_skipped(self):
        n = director.judge_and_record(["nope"], factory=self.factory,
                                      client_call=lambda s, u: '{"fit":1,"verdict":"keep","why":"x"}')
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
