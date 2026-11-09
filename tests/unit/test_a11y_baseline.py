"""The accessibility baseline logic (#168): what counts as new, fixed and known.

No browser: tests/accessibility/axe_baseline.py is pure. The scans themselves are in
tests/accessibility/test_accessibility.py and run only in the accessibility CI job.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

from tests.accessibility import axe_baseline as ab

pytestmark = pytest.mark.unit


def _violation(rule: str, count: int, impact: str = "serious") -> dict:
    return {"id": rule, "impact": impact, "help": f"help for {rule}", "helpUrl": f"https://axe/{rule}",
            "nodes": [{"target": [f".n{i}"], "html": f"<b class='n{i}'>x</b>"} for i in range(count)]}


def _entry(scenario: str, rule: str, nodes: int, note: str = "known") -> dict:
    return {"scenario": scenario, "rule": rule, "nodes": nodes, "note": note}


def _baseline(*entries: dict) -> ab.Baseline:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "b.json"
        path.write_text(json.dumps({"violations": list(entries)}), encoding="utf-8")
        return ab.load_baseline(path)


class Compare(unittest.TestCase):
    def test_nothing_found_and_nothing_recorded_is_ok(self):
        out = ab.compare("page", [], _baseline())
        self.assertTrue(out.ok)
        self.assertEqual((out.new, out.fixed, out.shrunk, out.known), ([], [], [], []))

    def test_a_violation_not_in_the_baseline_is_new_and_fails(self):
        out = ab.compare("page", [_violation("label", 1)], _baseline())
        self.assertFalse(out.ok)
        self.assertEqual(len(out.new), 1)
        self.assertIn("NEW label", out.new[0])

    def test_the_baseline_is_per_scenario(self):
        out = ab.compare("other", [_violation("label", 1)], _baseline(_entry("page", "label", 1)))
        self.assertEqual(len(out.new), 1, "a rule known on one page is new on another")
        self.assertEqual(out.fixed, [], "and the other page's entry is not this scenario's to judge")

    def test_exactly_as_recorded_is_known_and_passes(self):
        out = ab.compare("page", [_violation("label", 2)], _baseline(_entry("page", "label", 2, "why")))
        self.assertTrue(out.ok)
        self.assertEqual(len(out.known), 1)
        self.assertIn("why", out.known[0])

    def test_more_elements_than_recorded_is_a_regression(self):
        out = ab.compare("page", [_violation("label", 3)], _baseline(_entry("page", "label", 2)))
        self.assertFalse(out.ok)
        self.assertIn("MORE ELEMENTS than the baseline's 2", out.new[0])

    def test_fewer_elements_is_a_notice_not_a_failure(self):
        out = ab.compare("page", [_violation("label", 1)], _baseline(_entry("page", "label", 2)))
        self.assertTrue(out.ok)
        self.assertEqual(len(out.shrunk), 1)

    def test_a_recorded_rule_that_no_longer_fails_must_be_removed(self):
        out = ab.compare("page", [], _baseline(_entry("page", "label", 2, "was broken")))
        self.assertFalse(out.ok)
        self.assertIn("delete its entry", out.fixed[0])
        self.assertIn("was broken", out.fixed[0])

    def test_new_and_fixed_are_reported_together(self):
        out = ab.compare("page", [_violation("region", 1)], _baseline(_entry("page", "label", 1)))
        self.assertEqual((len(out.new), len(out.fixed)), (1, 1))


class Describe(unittest.TestCase):
    def test_lists_a_few_elements_and_counts_the_rest(self):
        text = ab.describe(_violation("label", 5), limit=2)
        self.assertIn("label (serious) on 5 element(s)", text)
        self.assertIn(".n0", text)
        self.assertIn(".n1", text)
        self.assertNotIn(".n2", text)
        self.assertIn("and 3 more", text)
        self.assertIn("https://axe/label", text)


class LoadBaseline(unittest.TestCase):
    def _load(self, *entries):
        return _baseline(*entries)

    def test_rejects_a_rule_listed_twice_for_a_scenario(self):
        with self.assertRaisesRegex(ValueError, "listed twice"):
            self._load(_entry("p", "label", 1), _entry("p", "label", 2))

    def test_rejects_an_entry_without_a_positive_count(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            self._load(_entry("p", "label", 0))

    def test_rejects_an_entry_without_a_note(self):
        with self.assertRaisesRegex(ValueError, "note"):
            self._load(_entry("p", "label", 1, note=""))


class RecordedBaseline(unittest.TestCase):
    """known_violations.json itself: well formed, and about scenarios that exist."""

    def test_is_valid_and_names_real_scenarios(self):
        baseline = ab.load_baseline()
        source = (Path(ab.__file__).with_name("test_accessibility.py")).read_text(encoding="utf-8")
        for scenario, rule in baseline:
            with self.subTest(scenario=scenario, rule=rule):
                self.assertIn(f'"{scenario}"', source, "no scan uses this scenario name")

    def test_scans_wcag_21_a_and_aa(self):
        self.assertEqual(ab.WCAG_21_AA_TAGS, ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])


if __name__ == "__main__":
    unittest.main()
