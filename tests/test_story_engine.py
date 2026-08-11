from __future__ import annotations

import unittest

from modules.media_story import enrich_story_with_media
from modules.story_engine import (
    analyze_story,
    build_chapters,
    build_quality_report,
    infer_stream_type,
    match_required_events,
    select_story_sections,
    suggest_flashbacks,
)


class StoryEngineTests(unittest.TestCase):
    def setUp(self):
        self.transcript = {"segments": [
            {"start": 0, "end": 12, "text": "Today we start the Rocomamas challenge and explain the rules."},
            {"start": 14, "end": 30, "text": "First we need to finish the meal before the timer."},
            {"start": 90, "end": 110, "text": "But then the challenge gets harder and we have a problem."},
            {"start": 112, "end": 126, "text": "Wait bro what is happening, this is crazy?"},
            {"start": 240, "end": 260, "text": "Remember what I said earlier about the final round."},
            {"start": 400, "end": 425, "text": "Finally we did it, we won the challenge, yes!"},
        ]}

    def test_analysis_finds_setup_escalation_callback_and_payoff(self):
        graph = analyze_story(self.transcript, "Rocomamas challenge final result")
        roles = {beat["role"] for beat in graph["beats"]}
        self.assertIn("setup", roles)
        self.assertIn("escalation", roles)
        self.assertIn("callback", roles)
        self.assertIn("payoff", roles)
        self.assertTrue(all(beat["boundaryEvidence"]["firstSegment"] for beat in graph["beats"]))

    def test_analysis_builds_an_explainable_dramatic_arc(self):
        graph = analyze_story(self.transcript, "Rocomamas challenge final result")
        arc = {stage["stage"]: stage for stage in graph["narrativeArc"]}
        self.assertEqual(set(arc), {"setup", "rising_action", "tension", "climax", "resolution"})
        self.assertTrue(arc["setup"]["beatIds"])
        self.assertTrue(arc["tension"]["beatIds"])
        self.assertTrue(arc["climax"]["beatIds"])
        self.assertLess(arc["setup"]["sourceStart"], arc["climax"]["sourceStart"])
        self.assertTrue(all("narrativeStage" in beat for beat in graph["beats"]))

    def test_challenge_format_and_required_event_are_preserved(self):
        transcript = {"segments": [
            {"start": 0, "end": 20, "text": "Today we start the wing challenge and explain the rules."},
            {"start": 120, "end": 150, "text": "The first attempt gets difficult and everyone is worried."},
            {"start": 500, "end": 540, "text": "Ice starts eating the wings now and the spice hits him hard."},
            {"start": 700, "end": 730, "text": "Finally the winner finishes and everyone reacts."},
        ]}
        graph = analyze_story(transcript, "Tell the full wing challenge story")
        inferred = infer_stream_type(graph, "wing challenge")
        self.assertEqual(inferred["inferredType"], "challenge")
        matches = match_required_events(graph, ["Ice eating part"])
        self.assertTrue(matches[0]["matched"])
        sections = select_story_sections(graph, target_seconds=180, max_sections=6)
        self.assertTrue(any("Ice eating part" in section.get("requiredEvents", []) for section in sections))
        report = build_quality_report(sections, graph, target_seconds=180)
        required = report["metrics"]["requiredEventCoverage"][0]
        self.assertTrue(required["included"])
        self.assertFalse(any(item["code"].startswith("required_event_") for item in report["warnings"]))

    def test_selection_preserves_setup_and_payoff_in_chronological_order(self):
        graph = analyze_story(self.transcript, "challenge result")
        sections = select_story_sections(graph, target_seconds=180, max_sections=5)
        self.assertGreaterEqual(len(sections), 2)
        self.assertEqual(sections, sorted(sections, key=lambda section: section["start"]))
        selected_roles = {role for section in sections for role in section["roles"]}
        self.assertIn("setup", selected_roles)
        self.assertIn("payoff", selected_roles)

    def test_chapters_map_source_ranges_to_contiguous_timeline(self):
        sections = [
            {"start": 10, "end": 40, "duration": 30, "title": "Setup", "role": "setup", "beatIds": ["beat_1"]},
            {"start": 300, "end": 345, "duration": 45, "title": "Payoff", "role": "payoff", "beatIds": ["beat_9"]},
        ]
        chapters = build_chapters(sections)
        self.assertEqual(chapters[0]["timelineStart"], 0)
        self.assertEqual(chapters[1]["timelineStart"], 30)
        self.assertEqual(chapters[1]["timelineEnd"], 75)
        self.assertEqual(chapters[1]["sourceStart"], 300)

    def test_flashback_suggestions_prefer_later_payoffs(self):
        graph = analyze_story(self.transcript, "challenge result")
        suggestions = suggest_flashbacks(graph, limit=2)
        self.assertTrue(suggestions)
        self.assertTrue(any(item["role"] == "payoff" for item in suggestions))
        self.assertTrue(all(item["sourceEnd"] - item["sourceStart"] <= 12 for item in suggestions))

    def test_media_signals_mark_visually_active_beats(self):
        graph = analyze_story(self.transcript, "challenge result")
        enrich_story_with_media(graph, {
            "version": 1,
            "fingerprint": "test",
            "sceneCuts": [{"at": 91, "score": .4}, {"at": 95, "score": .3}],
            "blackSegments": [{"start": 100, "end": 101, "duration": 1}],
        })
        beat = next(item for item in graph["beats"] if item["start"] <= 91 < item["end"])
        self.assertEqual(beat["mediaSignals"]["sceneCuts"], 2)
        self.assertEqual(beat["mediaSignals"]["blackSegments"], 1)
        self.assertEqual(graph["mediaAnalysis"]["sceneCutCount"], 2)

    def test_quality_report_flags_late_opening_and_large_source_jump(self):
        graph = analyze_story(self.transcript, "challenge result")
        sections = [
            {"start": 90, "end": 110, "duration": 20, "role": "setup", "roles": ["setup"]},
            {"start": 400, "end": 425, "duration": 25, "role": "payoff", "roles": ["payoff"]},
        ]
        report = build_quality_report(sections, graph, target_seconds=180)
        codes = {item["code"] for item in report["warnings"]}
        self.assertIn("late_opening", codes)
        self.assertIn("large_source_jump", codes)
        self.assertIn("target_shortfall", codes)
        self.assertEqual(report["grade"], "review")


if __name__ == "__main__":
    unittest.main()
