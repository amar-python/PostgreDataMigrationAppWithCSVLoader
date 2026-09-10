"""Unit tests for the Tier E (O-07) and Tier X (O-08) eval logic.

The scenarios themselves need PostgreSQL (Tier E) or read a repo file (Tier X),
but the comparison logic inside them is pure and is where the bugs would live. A
parity check that silently returns "no differences" for two different schemas is
worse than no check, so the negative controls here matter more than the positive
ones: each asserts that a specific kind of drift is actually caught.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import runner  # noqa: E402


@pytest.mark.unit
class TierEDiffSignatures(unittest.TestCase):
    """O-07: cross-environment structural comparison."""

    def test_identical_schemas_report_no_differences(self):
        sig = {"organisations": ["org_id:uuid:NO", "name:text:NO"]}
        self.assertEqual(runner._diff_signatures("dev", sig, "prod", dict(sig)), [])

    def test_namespace_is_not_part_of_the_comparison(self):
        # The whole point of BR-01: two envs differing only in schema name are equal.
        dev = {"organisations": ["org_id:uuid:NO"]}
        prod = {"organisations": ["org_id:uuid:NO"]}
        self.assertEqual(runner._diff_signatures("dev", dev, "prod", prod), [])

    def test_missing_table_is_caught(self):
        dev = {"organisations": ["a:text:NO"], "personnel": ["b:text:NO"]}
        prod = {"organisations": ["a:text:NO"]}
        diffs = runner._diff_signatures("dev", dev, "prod", prod)
        self.assertTrue(any("missing tables" in d and "personnel" in d for d in diffs))

    def test_extra_table_is_caught(self):
        dev = {"organisations": ["a:text:NO"]}
        prod = {"organisations": ["a:text:NO"], "rogue_table": ["x:text:YES"]}
        diffs = runner._diff_signatures("dev", dev, "prod", prod)
        self.assertTrue(any("rogue_table" in d for d in diffs))

    def test_added_column_is_caught(self):
        # The exact scenario VCRM_GAPS.md named: someone edits env_staging.sql.
        dev = {"organisations": ["org_id:uuid:NO"]}
        staging = {"organisations": ["org_id:uuid:NO", "sneaky_col:text:YES"]}
        diffs = runner._diff_signatures("dev", dev, "staging", staging)
        self.assertTrue(any("sneaky_col" in d for d in diffs))

    def test_changed_type_is_caught(self):
        dev = {"organisations": ["org_id:uuid:NO"]}
        prod = {"organisations": ["org_id:text:NO"]}
        diffs = runner._diff_signatures("dev", dev, "prod", prod)
        self.assertEqual(len(diffs), 1)
        self.assertIn("organisations", diffs[0])

    def test_changed_nullability_is_caught(self):
        dev = {"organisations": ["name:text:NO"]}
        prod = {"organisations": ["name:text:YES"]}
        self.assertTrue(runner._diff_signatures("dev", dev, "prod", prod))

    def test_reordered_columns_are_caught_as_drift(self):
        # Same column set, different ordinal position. Anything doing SELECT *
        # or positional COPY would behave differently between the two.
        dev = {"organisations": ["a:text:NO", "b:text:NO"]}
        prod = {"organisations": ["b:text:NO", "a:text:NO"]}
        diffs = runner._diff_signatures("dev", dev, "prod", prod)
        self.assertEqual(len(diffs), 1)
        self.assertIn("ordinal order", diffs[0])

    def test_env_targets_cover_all_four_environments(self):
        names = [e[0] for e in runner.ENV_TARGETS]
        self.assertEqual(names, ["dev", "test", "staging", "prod"])
        # Every env must have a distinct database AND schema, or "isolated
        # environments" is not what is actually deployed.
        self.assertEqual(len({e[1] for e in runner.ENV_TARGETS}), 4)
        self.assertEqual(len({e[2] for e in runner.ENV_TARGETS}), 4)


@pytest.mark.unit
class TierXSqliteStructure(unittest.TestCase):
    """O-08: SQLite DDL execution and structural readback."""

    def test_placeholders_are_substituted(self):
        out = runner._substitute_placeholders(
            "CREATE TABLE {{TBL_ORGANISATIONS}} (x TEXT);"
        )
        self.assertIn("organisations", out)
        self.assertNotIn("{{", out)

    def test_every_known_table_has_a_substitution(self):
        ddl = " ".join("{{TBL_" + t.upper() + "}}"
                       for t in runner._ENGINE_PLACEHOLDER_TABLES)
        self.assertNotIn("{{", runner._substitute_placeholders(ddl))

    def test_unknown_placeholder_survives_so_the_scenario_can_flag_it(self):
        out = runner._substitute_placeholders("{{TBL_NOT_A_REAL_TABLE}}")
        self.assertIn("{{TBL_NOT_A_REAL_TABLE}}", out)

    def test_structure_is_read_back_from_executed_ddl(self):
        got = runner._sqlite_structure(
            "CREATE TABLE alpha (id TEXT PRIMARY KEY, name TEXT NOT NULL);"
            "CREATE TABLE beta (ref TEXT);"
        )
        self.assertNotIn("error", got)
        self.assertEqual(sorted(got["tables"]), ["alpha", "beta"])
        self.assertEqual(got["tables"]["alpha"], ["id", "name"])

    def test_invalid_ddl_is_reported_rather_than_raised(self):
        got = runner._sqlite_structure("CREATE TABLE (((;")
        self.assertIn("error", got)

    def test_sqlite_internal_tables_are_excluded(self):
        got = runner._sqlite_structure(
            "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT);"
        )
        # AUTOINCREMENT creates sqlite_sequence; it is not part of the schema.
        self.assertEqual(sorted(got["tables"]), ["t"])

    def test_the_real_sqlite_ddl_executes_and_matches_the_expectation_file(self):
        import json
        root = Path(__file__).resolve().parent.parent
        ddl = (root / "build" / "schema" / "sqlite"
               / "te_core_schema.sql").read_text(encoding="utf-8")
        exp = json.loads(
            (root / "evals" / "expected" / "tier_x"
             / "01_sqlite_schema_structure.json").read_text(encoding="utf-8")
        )["expected"]

        got = runner._sqlite_structure(runner._substitute_placeholders(ddl))
        self.assertNotIn("error", got, "the shipped SQLite DDL must execute")
        self.assertEqual(sorted(got["tables"]), sorted(exp["expected_tables"]))

    def test_known_missing_tables_are_genuinely_absent(self):
        # Guards the honesty of the expectation file: if someone adds one of
        # these tables to the DDL but forgets to move it out of
        # known_missing_tables, the file would misreport the shortfall.
        import json
        root = Path(__file__).resolve().parent.parent
        ddl = (root / "build" / "schema" / "sqlite"
               / "te_core_schema.sql").read_text(encoding="utf-8")
        exp = json.loads(
            (root / "evals" / "expected" / "tier_x"
             / "01_sqlite_schema_structure.json").read_text(encoding="utf-8")
        )["expected"]
        got = runner._sqlite_structure(runner._substitute_placeholders(ddl))
        for table in exp["known_missing_tables"]:
            self.assertNotIn(
                table, got["tables"],
                f"{table} is listed as missing but the DDL now defines it — "
                "move it into expected_tables",
            )

    def test_missing_plus_present_accounts_for_all_twelve_tables(self):
        import json
        root = Path(__file__).resolve().parent.parent
        exp = json.loads(
            (root / "evals" / "expected" / "tier_x"
             / "01_sqlite_schema_structure.json").read_text(encoding="utf-8")
        )["expected"]
        total = set(exp["expected_tables"]) | set(exp["known_missing_tables"])
        self.assertEqual(
            total, set(runner._ENGINE_PLACEHOLDER_TABLES),
            "the expectation file must account for every T&E table, so the "
            "shortfall cannot be understated by omission",
        )


@pytest.mark.unit
class TierRegistration(unittest.TestCase):
    """Both new tiers must be reachable from the CLI."""

    def test_all_five_tiers_are_registered(self):
        self.assertEqual(sorted(runner.TIER_RUNNERS), ["e", "i", "p", "s", "x"])
