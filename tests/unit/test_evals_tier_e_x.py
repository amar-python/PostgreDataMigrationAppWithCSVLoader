"""Unit tests for the Tier E (O-07) and Tier X (O-08) eval logic.

The scenarios themselves need PostgreSQL (Tier E) or read a repo file (Tier X),
but the comparison logic inside them is pure and is where the bugs would live. A
parity check that silently returns "no differences" for two different schemas is
worse than no check, so the negative controls here matter more than the positive
ones: each asserts that a specific kind of drift is actually caught.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

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
class TierEColumnSignatureQuery(unittest.TestCase):
    """Issue #45: the schema query itself, not just the comparison.

    psql never interpolates :'var' inside -c, so the query must go on stdin, and
    a failed query must not be reported as an empty schema.
    """

    def _scenario(self, completed):
        expected = {"expected": {"min_tables_per_env": 12},
                    "envs_under_test": ["dev"]}
        result = runner.ScenarioResult(tier="e", name="t")
        with patch.object(runner, "_deploy_env",
                          return_value={"env": "dev", "exit_code": 0}), \
             patch.object(runner.subprocess, "run", return_value=completed) as run:
            runner._run_envs_have_identical_structure(result, expected)
        return result, run

    def test_query_is_sent_on_stdin_not_via_dash_c(self):
        ok = subprocess.CompletedProcess([], 0, stdout="t|c|text|NO\n", stderr="")
        _, run = self._scenario(ok)
        args, kwargs = run.call_args
        self.assertNotIn("-c", args[0])
        self.assertIn(":'sch'", kwargs["input"])

    def test_query_failure_is_reported_as_a_query_error(self):
        bad = subprocess.CompletedProcess([], 1, stdout="",
                                          stderr='ERROR:  syntax error at or near ":"')
        result, _ = self._scenario(bad)
        self.assertFalse(result.passed)
        self.assertTrue(any("schema query" in e and "syntax error" in e
                            for e in result.errors), result.errors)

    def test_genuinely_empty_schema_still_fails(self):
        empty = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        result, _ = self._scenario(empty)
        self.assertFalse(result.passed)
        self.assertIn("env dev has 0 tables in its schema, expected >= 12 "
                      "(deploy may have partially failed)", result.errors)


@pytest.mark.unit
class TierEEmptySchemaControl(unittest.TestCase):
    """Scenario 02, the negative control for scenario 01.

    Against a real server it proves scenario 01 can see "a deploy wrote nothing".
    Here psql and the schema query are mocked, to pin the control's own logic:
    above all that it FAILS when the comparison stops reporting an empty schema,
    since a control that cannot fail is worth nothing.
    """

    REF = {"t%d" % i: ["id:uuid:NO"] for i in range(12)}
    EXPECTED = {
        "reference_env": "dev",
        "expected": {"min_reference_tables": 12, "empty_schema_tables": 0,
                     "diff_reports_missing_tables": True},
    }

    def _run(self, signatures, psql=None, diff=None, expected=None):
        """Run the control; returns (result, psql mock, signature mock)."""
        ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        result = runner.ScenarioResult(tier="e", name="02_empty_schema_is_detected")
        with patch.object(runner, "_column_signature", side_effect=signatures) as sig, \
             patch.object(runner, "_psql_run",
                          **({"side_effect": psql} if psql else {"return_value": ok})) as run:
            if diff is None:
                runner._run_empty_schema_negative_control(result, expected or self.EXPECTED)
            else:
                with patch.object(runner, "_diff_signatures", return_value=diff):
                    runner._run_empty_schema_negative_control(result, expected or self.EXPECTED)
        return result, run, sig

    @staticmethod
    def _sql(run):
        return [c.args[1] for c in run.call_args_list]

    def test_passes_when_an_empty_schema_reads_empty_and_the_comparison_flags_it(self):
        result, run, _ = self._run([self.REF, {}])
        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.actual["reference_tables"], 12)
        self.assertEqual(result.actual["empty_schema_tables"], 0)
        self.assertGreaterEqual(result.actual["differences_reported"], 1)

    def test_fails_when_the_comparison_no_longer_reports_the_missing_tables(self):
        # The point of a control: neutralise the thing it guards and it must go red.
        result, _, _ = self._run([self.REF, {}], diff=[])
        self.assertFalse(result.passed)
        self.assertTrue(any("would pass a deploy that wrote nothing" in e
                            for e in result.errors), result.errors)

    def test_fails_when_an_empty_schema_reports_tables(self):
        result, _, _ = self._run([self.REF, {"x": ["id:uuid:NO"]}])
        self.assertFalse(result.passed)
        self.assertIn("an empty schema returned 1 tables, expected 0", result.errors)

    def test_a_failed_query_on_the_empty_schema_is_not_read_as_no_tables(self):
        result, _, _ = self._run([self.REF, RuntimeError("connection lost")])
        self.assertFalse(result.passed)
        self.assertTrue(any("must not be reported as 'no tables'" in e
                            and "connection lost" in e for e in result.errors), result.errors)

    def test_refuses_to_run_against_an_empty_reference_and_creates_nothing(self):
        result, run, _ = self._run([{}])
        self.assertFalse(result.passed)
        self.assertTrue(any("Deploy it first" in e for e in result.errors), result.errors)
        run.assert_not_called()

    def test_a_failed_reference_query_is_reported_and_creates_nothing(self):
        result, run, _ = self._run([RuntimeError("db down")])
        self.assertFalse(result.passed)
        self.assertIn("reference env dev: db down", result.errors)
        run.assert_not_called()

    def test_creates_then_drops_the_throwaway_schema(self):
        _, run, _ = self._run([self.REF, {}])
        sql = self._sql(run)
        self.assertEqual(len(sql), 2)
        self.assertIn("CREATE SCHEMA", sql[0])
        self.assertTrue(sql[1].startswith("DROP SCHEMA IF EXISTS"))
        self.assertIn(runner._EMPTY_CONTROL_SCHEMA, sql[1])

    def test_drops_the_throwaway_schema_even_when_the_check_fails(self):
        _, run, _ = self._run([self.REF, RuntimeError("boom")])
        self.assertTrue(self._sql(run)[-1].startswith("DROP SCHEMA IF EXISTS"))

    def test_never_drops_with_cascade(self):
        _, run, _ = self._run([self.REF, {}])
        self.assertFalse(any("CASCADE" in q.upper() for q in self._sql(run)), self._sql(run))

    def test_a_failed_drop_is_reported(self):
        ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        bad = subprocess.CompletedProcess([], 1, stdout="", stderr="ERROR: cannot drop")
        result, _, _ = self._run([self.REF, {}], psql=[ok, bad])
        self.assertFalse(result.passed)
        self.assertTrue(any("could not drop the throwaway schema" in e
                            and "cannot drop" in e for e in result.errors), result.errors)

    def test_a_failed_create_is_reported_and_no_schema_query_is_run_on_it(self):
        bad = subprocess.CompletedProcess([], 1, stdout="", stderr="ERROR: permission denied")
        result, _, sig = self._run([self.REF], psql=[bad])
        self.assertFalse(result.passed)
        self.assertTrue(any("could not create the throwaway schema" in e
                            for e in result.errors), result.errors)
        self.assertEqual(sig.call_count, 1, "only the reference was queried")

    def test_an_unknown_reference_env_is_reported(self):
        result, run, _ = self._run([], expected={"reference_env": "nope", "expected": {}})
        self.assertFalse(result.passed)
        self.assertTrue(any("not one of the environments" in e for e in result.errors))
        run.assert_not_called()

    def test_the_scenario_is_dispatched_by_name(self):
        scenario = Path("evals/datasets/tier_e/02_empty_schema_is_detected")
        with patch.object(runner, "_load_expected", return_value={"expected": {}}), \
             patch.object(runner, "_can_connect_pg", return_value=True), \
             patch.object(runner, "_run_empty_schema_negative_control") as control:
            runner.run_tier_e_scenario(scenario)
        control.assert_called_once()

    def test_an_unknown_tier_e_scenario_is_still_an_error(self):
        with patch.object(runner, "_load_expected", return_value={"expected": {}}), \
             patch.object(runner, "_can_connect_pg", return_value=True):
            result = runner.run_tier_e_scenario(Path("evals/datasets/tier_e/99_unknown"))
        self.assertIn("Unknown tier-E scenario: 99_unknown", result.errors)

    def test_the_scenario_files_exist_and_agree(self):
        root = Path(__file__).resolve().parents[2] / "evals"
        self.assertTrue((root / "datasets/tier_e/02_empty_schema_is_detected/NOTES.txt").is_file())
        expected = runner._load_expected("e", "02_empty_schema_is_detected")
        self.assertEqual(expected["scenario"], "02_empty_schema_is_detected")
        self.assertEqual(expected["expected"]["empty_schema_tables"], 0)
        self.assertIs(expected["expected"]["diff_reports_missing_tables"], True)


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
        root = Path(__file__).resolve().parents[2]
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
        root = Path(__file__).resolve().parents[2]
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
        root = Path(__file__).resolve().parents[2]
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
