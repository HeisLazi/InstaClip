"""Creator Language Pack — slang glossary + review seeding + import/export.

Uses a temp pack file so the real one is never touched.
"""

import tempfile
import unittest
from pathlib import Path

from modules import language_pack as lp


class LanguagePackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = lp.PACK_FILE
        lp.PACK_FILE = Path(self._tmp.name) / "language_pack.json"

    def tearDown(self):
        lp.PACK_FILE = self._orig
        self._tmp.cleanup()

    def test_add_and_list(self):
        lp.add_term("Tsek", "go away (rude)", lang="af", aliases=["Futsek"])
        terms = lp.list_terms()
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]["term"], "tsek")            # normalized
        self.assertEqual(terms[0]["aliases"], ["futsek"])

    def test_upsert_by_term(self):
        lp.add_term("tsek", "v1")
        lp.add_term("tsek", "v2")
        self.assertEqual(len(lp.list_terms()), 1)
        self.assertEqual(lp.list_terms()[0]["meaning"], "v2")

    def test_manual_wins_over_derived(self):
        lp.add_term("tsek", "manual meaning", source="manual")
        lp.add_term("tsek", "derived meaning", source="derived_reviews")
        self.assertEqual(lp.list_terms()[0]["meaning"], "manual meaning")

    def test_delete(self):
        lp.add_term("tsek", "go away")
        self.assertTrue(lp.delete_term("TSEK"))
        self.assertEqual(lp.list_terms(), [])
        self.assertFalse(lp.delete_term("nope"))

    def test_hotwords_include_terms_and_aliases(self):
        lp.add_term("tsek", "go away", aliases=["futsek"])
        lp.add_term("jitta", "guy")
        hw = lp.whisper_hotwords()
        self.assertIn("tsek", hw)
        self.assertIn("futsek", hw)
        self.assertIn("jitta", hw)

    def test_glossary_block(self):
        self.assertEqual(lp.glossary_for_llm(), "")
        lp.add_term("ma se poes", "vulgar insult", lang="afrikaans")
        block = lp.glossary_for_llm()
        self.assertIn("ma se poes", block)
        self.assertIn("vulgar insult", block)
        self.assertIn("afrikaans", block)

    def test_seed_from_reviews_extracts_definitions(self):
        import modules.clip_reviews as cr
        fake = [
            {"notes": "its ma se poes = your moms a bitch in afrikaans. also just too short"},
            {"notes": "so i tought him tsek which is like go away but in a very rude way"},
            {"notes": "goons means porn btw"},
            {"notes": "this clip cut too early, needs the ending"},  # no definition
        ]
        orig = cr.list_reviews
        cr.list_reviews = lambda *a, **k: fake
        try:
            res = lp.seed_from_reviews()
        finally:
            cr.list_reviews = orig
        terms = {t["term"]: t for t in lp.list_terms()}
        self.assertIn("ma se poes", terms)
        self.assertEqual(terms["ma se poes"]["lang"], "afrikaans")
        self.assertIn("tsek", terms)
        self.assertIn("goons", terms)
        self.assertTrue(all(t["source"] == "derived_reviews" for t in terms.values()))
        self.assertGreaterEqual(res["added"], 3)

    def test_export_import_round_trip(self):
        lp.add_term("tsek", "go away", lang="af")
        pack = lp.export_pack()
        self.assertEqual(pack["kind"], "lek_language_pack")
        lp.PACK_FILE = Path(self._tmp.name) / "other.json"   # fresh pack
        res = lp.import_pack(pack, mode="replace")
        self.assertEqual(res["imported"], 1)
        self.assertEqual(lp.list_terms()[0]["term"], "tsek")

    def test_import_rejects_bad_payload(self):
        with self.assertRaises(ValueError):
            lp.import_pack({"nope": 1})


if __name__ == "__main__":
    unittest.main()
