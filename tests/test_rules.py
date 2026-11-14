import unittest
from datetime import datetime as D
from edu_support import rules, config as C


class Rules(unittest.TestCase):
    def test_stem_plural(self):
        self.assertEqual(rules.stem("fees"), rules.stem("fee"))
        self.assertEqual(rules.stem("passwords"), rules.stem("password"))

    def test_unsupported_numbers_detects_invented_figure(self):
        self.assertEqual(rules.unsupported_numbers("The fee is 50 dollars", ["Late fee: 25 dollars"]), ["50"])

    def test_supported_numbers_pass(self):
        self.assertEqual(rules.unsupported_numbers("The fee is 25 dollars", ["Late fee: 25 dollars"]), [])

    def test_effective_article_picks_version_in_force(self):
        v = [{"article_id": "A", "effective_from": D(2026, 1, 1).date(), "effective_to": D(2026, 6, 30).date(), "version_no": 1},
             {"article_id": "B", "effective_from": D(2026, 7, 1).date(), "effective_to": None, "version_no": 2}]
        self.assertEqual(rules.effective_article(v, D(2026, 6, 30, 12))["article_id"], "A")
        self.assertEqual(rules.effective_article(v, D(2026, 7, 1))["article_id"], "B")
        self.assertIsNone(rules.effective_article(v, D(2025, 12, 31)))

    def test_priority_urgent_when_deadline_close(self):
        p, why = rules.derive_priority("normal", D(2026, 10, 5, 10), D(2026, 10, 6).date(), "need help")
        self.assertIn(p, ("urgent", "high"))
        self.assertTrue(why)

    def test_transitions_table_is_closed(self):
        for a, tos in C.TRANSITIONS.items():
            self.assertTrue(set(tos) <= set(C.STATUSES))
        self.assertNotIn("new", C.TRANSITIONS["closed"])


if __name__ == "__main__":
    unittest.main()
