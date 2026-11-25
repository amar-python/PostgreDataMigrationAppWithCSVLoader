"""#303 (OIT-018): the Tier S threshold must equal the number of assertions in the SQL suite.

Tier S fails when the suite reports fewer assertions than ``min_total_assertions``. The threshold was left at 142 while
the suite grew to 159, so up to 17 assertions could be deleted without failing the gate. This test counts the
assertions in ``tests/suites/*.sql`` as text (no database) and requires the threshold to match exactly:

  * deleting an assertion makes the count lower than the threshold here, and Tier S fails on the database side;
  * adding one makes this test fail until the threshold is raised, so the gate keeps covering the new assertion.

What counts as one assertion, as the framework records it (``tests/framework/test_framework.sql``):

  * each ``assert_<kind>(`` call in a suite;
  * each distinct test name passed to ``tf_record(`` directly. Suite 06 writes each of those as a pass branch and a
    fail branch of the same name, and only one of the two runs.

Lines that are SQL comments (``--``) are ignored. The count matched the live run on 24 Nov 2026: 159 assertion rows in
``te_test_harness.test_run_results`` on PostgreSQL 16 (153 ``assert_*`` calls and 6 ``tf_record`` names).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
SUITES = sorted((ROOT / "tests" / "suites").glob("test_*.sql"))
EXPECTED = ROOT / "evals" / "expected" / "tier_s" / "01_fresh_deploy_then_all_tests_pass.json"

_ASSERT = re.compile(r"\bassert_[a-z_]+\s*\(")
_TF_RECORD = re.compile(r"\btf_record\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'")


def _code(text: str) -> str:
    """The suite without its SQL line comments."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def count_assertions(sql: str) -> int:
    code = _code(sql)
    return len(_ASSERT.findall(code)) + len(set(_TF_RECORD.findall(code)))


def test_suites_are_found():
    assert len(SUITES) >= 6, f"expected the six SQL suites under tests/suites, found {[p.name for p in SUITES]}"


def test_tier_s_threshold_equals_the_assertions_in_the_suites():
    per_suite = {p.name: count_assertions(p.read_text(encoding="utf-8")) for p in SUITES}
    total = sum(per_suite.values())
    threshold = json.loads(EXPECTED.read_text(encoding="utf-8"))["expected"]["min_total_assertions"]
    assert threshold == total, (
        f"{EXPECTED.relative_to(ROOT)} has min_total_assertions {threshold}, but tests/suites/*.sql has {total} "
        f"assertions ({per_suite}). Set the threshold to {total} and update BR-20 in docs/VCRM.md, so the gate "
        "fails if an assertion disappears.")


def test_the_count_sees_a_removed_assertion():
    """Negative control on the counter itself: dropping one assert_ call lowers the count by one."""
    sql = SUITES[0].read_text(encoding="utf-8")
    before = count_assertions(sql)
    first = _ASSERT.search(_code(sql))
    assert first, f"{SUITES[0].name} has no assert_ call to remove"
    removed = sql.replace(first.group(0), "not_an_assertion(", 1)
    assert count_assertions(removed) == before - 1


def test_a_two_branch_tf_record_counts_once():
    sql = (
        "IF ok THEN PERFORM tf_record('s', 'X01 — it''s rejected', 'PASS', NULL, NULL, NULL);\n"
        "ELSE PERFORM tf_record('s', 'X01 — it''s rejected', 'FAIL', NULL, NULL, 'no error'); END IF;\n"
        "-- SELECT assert_true('s', 'commented out', true);\n"
    )
    assert count_assertions(sql) == 1
