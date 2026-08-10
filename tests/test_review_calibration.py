import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from modules import review_trainer
from modules.clip_judge import (
    _candidate_padding,
    _complete_candidate_end,
    _dedupe,
    _pad_candidate_window,
)
from modules.clip_reviews import classify_review_signal, summarize_reviews_for_llm
from modules.profiler.profiler import _review_adjusted_weight


class ReviewCalibrationTests(unittest.TestCase):
    def test_miss_is_not_positive_profile_evidence(self):
        self.assertIsNone(_review_adjusted_weight(1.0, {"verdict": "miss", "rating": 4}))

    def test_reviewed_keeper_gets_stronger_weight(self):
        self.assertEqual(
            _review_adjusted_weight(1.0, {"verdict": "keeper", "rating": 5}),
            6.0,
        )

    def test_candidate_window_keeps_edit_safe_context(self):
        self.assertEqual(_pad_candidate_window(10.0, 20.0, 60.0), (8.0, 24.0))

    def test_candidate_window_stays_inside_transcript(self):
        self.assertEqual(_pad_candidate_window(1.0, 19.0, 20.0), (0.0, 20.0))

    def test_candidate_end_snaps_forward_to_sentence_completion(self):
        segments = [
            {"start": 18.0, "end": 20.5, "text": "and then he opens the box"},
            {"start": 20.5, "end": 23.0, "text": "and realizes the prize is gone."},
            {"start": 23.1, "end": 26.0, "text": "chat starts a new topic"},
        ]

        end, reason = _complete_candidate_end(20.0, segments, 26.0)

        self.assertEqual(end, 23.0)
        self.assertEqual(reason, "sentence_end")

    def test_candidate_end_uses_natural_pause_without_punctuation(self):
        segments = [
            {"start": 18.0, "end": 21.0, "text": "that is when the joke finally lands"},
            {"start": 23.0, "end": 25.0, "text": "new conversation"},
        ]

        end, reason = _complete_candidate_end(20.0, segments, 25.0)

        self.assertEqual(end, 21.0)
        self.assertEqual(reason, "natural_pause")

    def test_candidate_end_respects_completion_cap(self):
        segments = [
            {"start": 19.0, "end": 24.0, "text": "still talking"},
            {"start": 24.0, "end": 40.0, "text": "a very long unrelated continuation."},
        ]

        end, reason = _complete_candidate_end(20.0, segments, 40.0, max_extension=6.0)

        self.assertEqual(end, 24.0)
        self.assertEqual(reason, "segment_boundary")

    def test_candidate_end_does_not_jump_across_existing_silence(self):
        segments = [
            {"start": 16.0, "end": 19.0, "text": "the payoff already finished"},
            {"start": 21.0, "end": 24.0, "text": "a new unrelated sentence."},
        ]

        end, reason = _complete_candidate_end(20.0, segments, 24.0)

        self.assertEqual(end, 20.0)
        self.assertEqual(reason, "existing_pause")

    def test_reaction_window_gets_wider_edit_handles(self):
        self.assertEqual(
            _candidate_padding({"clip_type": "reaction", "compilation": True}),
            (8.0, 12.0),
        )

    def test_compilation_one_liner_stays_tighter(self):
        self.assertEqual(
            _candidate_padding({"kind": "B_one_liner", "compilation": True}),
            (3.0, 7.0),
        )

    def test_offset_duplicates_merge_into_wider_window(self):
        picks = [
            {
                "start": "0:01:00",
                "end": "0:01:12",
                "the_bit": "Lazi rates the new song as nasty and disgusting",
                "clip_type": "reaction",
                "kind": "B_one_liner",
                "confidence": 0.9,
                "compilation": True,
            },
            {
                "start": "0:01:10",
                "end": "0:01:22",
                "the_bit": "The new song is called nasty and disgusting as praise",
                "clip_type": "reaction",
                "kind": "B_one_liner",
                "confidence": 0.8,
                "compilation": True,
            },
        ]

        merged = _dedupe(picks)

        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["start"], merged[0]["end"]), (60.0, 82.0))
        self.assertEqual(merged[0]["merged_candidates"], 2)

    def test_distinct_nearby_one_liners_remain_separate(self):
        picks = [
            {
                "start": 100,
                "end": 106,
                "the_bit": "Lazi calls the song tough",
                "clip_type": "reaction",
                "kind": "B_one_liner",
                "confidence": 0.9,
            },
            {
                "start": 108,
                "end": 114,
                "the_bit": "Chat reveals the blackjack balance",
                "clip_type": "reaction",
                "kind": "B_one_liner",
                "confidence": 0.8,
            },
        ]

        self.assertEqual(len(_dedupe(picks)), 2)

    def test_bad_trim_is_not_negative_taste_evidence(self):
        review = {
            "verdict": "miss",
            "rating": 1,
            "tags": ["bad trim good clip"],
            "notes": "add the beginning and more to the end",
        }
        self.assertEqual(classify_review_signal(review), "boundary")
        self.assertIsNone(_review_adjusted_weight(1.0, review))

    def test_random_audio_spike_is_a_true_negative(self):
        review = {
            "verdict": "miss",
            "notes": "No context, just a random moment with an audio spike",
        }
        self.assertEqual(classify_review_signal(review), "negative")

    def test_bare_miss_is_null_not_negative_taste_evidence(self):
        review = {"verdict": "miss", "tags": [], "reasons": [], "notes": ""}

        self.assertEqual(classify_review_signal(review), "null")
        self.assertIsNone(_review_adjusted_weight(1.0, review))

    def test_explained_miss_remains_negative(self):
        review = {"verdict": "miss", "reasons": ["weak payoff"]}

        self.assertEqual(classify_review_signal(review), "negative")

    def test_positive_tag_beats_low_rating(self):
        review = {
            "verdict": "undecided",
            "rating": 1,
            "tags": ["lwk good clip"],
        }
        self.assertEqual(classify_review_signal(review), "positive")
        self.assertEqual(_review_adjusted_weight(1.0, review), 3.0)

    @patch("modules.clip_reviews.list_reviews")
    def test_llm_summary_separates_boundary_failures_and_context(self, mocked_reviews):
        mocked_reviews.return_value = [
            {
                "stem": "trimmed",
                "verdict": "miss",
                "tags": ["bad trim good clip"],
                "notes": "good moment, extend the end",
            },
            {
                "stem": "music-slang",
                "verdict": "undecided",
                "notes": "in music reactions, nasty means the song is good",
            },
            {
                "stem": "noise",
                "verdict": "miss",
                "notes": "just a random moment, not a clip",
            },
        ]

        summary = summarize_reviews_for_llm()

        self.assertIn("BOUNDARY / CONTEXT FAILURES", summary)
        self.assertIn("RECENT USER CONTEXT / SLANG", summary)
        self.assertIn("TRUE MISSES", summary)
        self.assertIn("bad trim good clip", summary)


class ReviewTrainerTests(unittest.TestCase):
    @patch("modules.review_trainer.ollama_alive", return_value=True)
    @patch("modules.review_trainer.embed")
    @patch("modules.review_trainer.list_reviews")
    def test_training_is_verdict_first_and_excludes_review_text(
        self, mocked_reviews, mocked_embed, _mocked_ollama
    ):
        mocked_reviews.return_value = [
            {
                "stem": "keeper",
                "verdict": "keeper",
                "rating": 1,
                "notes": "low rated because compilation only",
            },
            {
                "stem": "bad-trim",
                "verdict": "miss",
                "rating": 1,
                "tags": ["bad trim good clip"],
                "notes": "extend the end",
            },
            {
                "stem": "true-miss",
                "verdict": "miss",
                "rating": 4,
                "notes": "random moment, not a clip",
            },
            {
                "stem": "null-miss",
                "verdict": "miss",
                "rating": 1,
            },
        ]
        mocked_embed.side_effect = lambda text: np.array([len(text), 1.0])

        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp)
            (transcript_dir / "keeper.txt").write_text("keeper transcript", encoding="utf-8")
            (transcript_dir / "bad-trim.txt").write_text("trimmed transcript", encoding="utf-8")
            (transcript_dir / "true-miss.txt").write_text("noise transcript", encoding="utf-8")
            (transcript_dir / "null-miss.txt").write_text("unexplained rejection", encoding="utf-8")
            with patch.object(review_trainer.paths, "CLIP_TRANSCRIPTS_DIR", transcript_dir):
                _x, labels, _metadata, texts = review_trainer.extract_training_data_from_reviews()

        self.assertEqual(labels.tolist(), [1, 0])
        self.assertEqual(texts, ["keeper transcript", "noise transcript"])
        mocked_embed.assert_any_call("keeper transcript")
        mocked_embed.assert_any_call("noise transcript")
        self.assertEqual(mocked_embed.call_count, 2)


if __name__ == "__main__":
    unittest.main()
