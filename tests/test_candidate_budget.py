import unittest

from modules.candidate_budget import DEFAULT_AUTO_CUT_TOP, select_auto_cut_candidates
from modules.pipeline_sync import DEFAULT_AUTO_PROMOTE_TOP


class CandidateBudgetTests(unittest.TestCase):
    def test_auto_cut_budget_matches_clip_room_promotion_budget(self):
        self.assertEqual(DEFAULT_AUTO_CUT_TOP, DEFAULT_AUTO_PROMOTE_TOP)

    def test_selects_top_ranked_candidates_without_mutating_input(self):
        highlights = [
            {"clip_id": "low", "final_score": 0.2},
            {"clip_id": "best", "final_score": 0.9},
            {"clip_id": "middle", "final_score": 0.6},
        ]
        original_order = [item["clip_id"] for item in highlights]

        selected = select_auto_cut_candidates(highlights, limit=2)

        self.assertEqual([item["clip_id"] for item in selected], ["best", "middle"])
        self.assertEqual([item["clip_id"] for item in highlights], original_order)

    def test_missing_scores_sort_last_and_zero_budget_cuts_nothing(self):
        highlights = [
            {"clip_id": "unknown"},
            {"clip_id": "scored", "quality_score": 0.5},
        ]

        self.assertEqual(
            [item["clip_id"] for item in select_auto_cut_candidates(highlights, limit=1)],
            ["scored"],
        )
        self.assertEqual(select_auto_cut_candidates(highlights, limit=0), [])


if __name__ == "__main__":
    unittest.main()
