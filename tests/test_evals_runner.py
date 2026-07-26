"""Unit tests for evals/runner.py.

Imports the runner module directly via importlib. Covers scenario discovery,
expected-file loading, tier_p/tier_i execution, row counting, and psql
availability. Most tests need no database; tier_i skip behaviour is verified
by mocking _can_connect_pg.
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "evals" / "runner.py"

spec = importlib.util.spec_from_file_location("evals_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(runner)


class EvalsRunnerTests(unittest.TestCase):
    def test_load_expected_returns_none_for_missing_scenario(self):
        """_load_expected with an unknown scenario name should return None without raising."""
        self.assertIsNone(runner._load_expected("p", "does_not_exist"))

    def test_discover_scenarios_filters_only_requested_name(self):
        """discover_scenarios with a name argument should return only the directory whose name matches exactly."""
        scenarios = runner.discover_scenarios("p", "01_happy_path")
        self.assertEqual([p.name for p in scenarios], ["01_happy_path"])

    def test_tier_p_reports_unknown_runner_action_as_failure(self):
        """An expected JSON with an unrecognised runner_action should produce a failed result containing 'Unknown runner_action' in errors."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scenario = tmp_path / "01_bad_action"
            expected_dir = tmp_path / "expected" / "tier_p"
            scenario.mkdir()
            expected_dir.mkdir(parents=True)
            (expected_dir / "01_bad_action.json").write_text(
                '{"scenario":"01_bad_action","runner_action":"nope","expected":{}}',
                encoding="utf-8",
            )

            with mock.patch.object(runner, "EXPECTED_DIR", tmp_path / "expected"):
                result = runner.run_tier_p_scenario(scenario)

        self.assertFalse(result.passed)
        self.assertIn("Unknown runner_action", result.errors[0])

    def test_tier_p_generated_invalid_utf8_skips_row_cleanly(self):
        """The 23_invalid_utf8_bytes eval scenario: an invalid-UTF-8 data row is
        skipped with a reason while valid rows still pass (exit_code=0), per the
        loader's load-what-is-valid contract. No raw Traceback may appear."""
        scenario = PROJECT_ROOT / "evals" / "datasets" / "tier_p" / "23_invalid_utf8_bytes"
        result = runner.run_tier_p_scenario(scenario)

        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.actual["exit_code"], 0)
        self.assertEqual(result.actual["skip_csv_row_count"], 1)
        self.assertNotIn("Traceback", result.actual["stderr"])

    def test_tier_i_fails_when_postgresql_is_unavailable(self):
        """When _can_connect_pg returns False, run_tier_i_scenario must FAIL (not skip): an unavailable prerequisite is a failure, so a green run always means the scenario really executed."""
        scenario = PROJECT_ROOT / "evals" / "datasets" / "tier_i" / "01_deploy_dev_twice"

        with mock.patch.object(runner, "_can_connect_pg", return_value=False):
            result = runner.run_tier_i_scenario(scenario)

        self.assertFalse(result.skipped)
        self.assertFalse(result.passed)
        self.assertIn("PostgreSQL not reachable", result.errors[0])

    def test_count_dev_rows_records_none_for_failed_count_query(self):
        """When the count query subprocess exits non-zero, _count_dev_rows should record None for every entry in DEV_SEED_TABLES."""
        fake_cp = mock.Mock(returncode=1, stdout="", stderr="relation missing")

        with mock.patch.object(runner.subprocess, "run", return_value=fake_cp):
            counts = runner._count_dev_rows()

        self.assertEqual(set(counts), set(runner._DEV_SEED_TABLES))
        self.assertTrue(all(value is None for value in counts.values()))

    def test_have_psql_uses_path_lookup(self):
        """When shutil.which returns None, _have_psql should return False."""
        with mock.patch.object(shutil, "which", return_value=None):
            self.assertFalse(runner._have_psql())


if __name__ == "__main__":
    unittest.main()
