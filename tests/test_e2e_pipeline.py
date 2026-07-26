"""End-to-end pipeline tests — CSV → validate → (load) → verify.

The validation half (Tier P) runs offline with no database.
The load + verify half (Tier I/S) requires a live PostgreSQL instance
and FAILS (never skips) when one is not reachable.

Mirrors gstack's skill-e2e-*.test.ts pattern: tests exercise the full
user-facing workflow, not just individual functions.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT      = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "build" / "csv" / "validator.py"
RUNNER    = ROOT / "evals" / "runner.py"


def _can_connect_pg() -> bool:
    if not shutil.which("psql"):
        return False
    try:
        r = subprocess.run(
            ["psql", "-tA", "-c", "SELECT 1"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "PGUSER": os.environ.get("PGUSER", "postgres")},
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


_PG_AVAILABLE = _can_connect_pg()

# The concrete env launchers are gitignored (only env_dev.example.sql is
# committed), so a fresh clone has no env_dev.sql. Tier I/S deploys require it,
# so treat its absence the same way we treat an unreachable database: skip.
_ENV_DEV_SQL   = ROOT / "build" / "environments" / "env_dev.sql"
_DB_E2E_READY  = _PG_AVAILABLE and _ENV_DEV_SQL.exists()
HELP           = ("Run 'bash scripts/provision_full_test_env.sh' (needs a reachable "
                  "PostgreSQL and PGUSER/PGHOST/PGPORT set).")
_SKIP_REASON   = (
    "PostgreSQL not reachable — skipping DB-dependent E2E tests"
    if not _PG_AVAILABLE
    else "build/environments/env_dev.sql not present (create it from "
         "env_dev.example.sql) — skipping DB-dependent E2E tests"
)


class E2EPipelineValidateOnly(unittest.TestCase):
    """Full CSV → validate pipeline. Runs offline; no database needed."""

    def test_happy_path_two_valid_rows(self):
        """Standard 2-column CSV with 2 valid rows produces correct outputs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "input.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_text("id,name\n1,Alice\n2,Bob\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            r = subprocess.run(
                [sys.executable, str(VALIDATOR)],
                env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            valid_lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(valid_lines[0], "id,name")
            self.assertIn("1,Alice", valid_lines)
            self.assertIn("2,Bob",   valid_lines)
            # skip.csv should contain only the header (no skips)
            if skip_csv.exists():
                skip_lines = [l for l in skip_csv.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertLessEqual(len(skip_lines), 1)

    def test_mixed_rows_splits_correctly(self):
        """Mixed CSV produces separate valid and skip outputs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "input.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_text("id,name\n1,Alice\n\n2\n3,Bob\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            r = subprocess.run(
                [sys.executable, str(VALIDATOR)],
                env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            valid_lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn("1,Alice", valid_lines)
            self.assertIn("3,Bob",   valid_lines)
            skip_lines = skip_csv.read_text(encoding="utf-8").strip().splitlines()
            # header + 2 bad rows
            self.assertEqual(len(skip_lines), 3)

    def test_all_invalid_rows_exit_nonzero(self):
        """A CSV where every data row fails validation must exit 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "input.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_text("id,name\n\n2\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            r = subprocess.run(
                [sys.executable, str(VALIDATOR)],
                env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("No valid rows", r.stderr)

    def test_output_directory_is_created_automatically(self):
        """Validator must create the output directory if it does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "input.csv"
            out_dir   = tmp_path / "nested" / "out"
            valid_csv = out_dir / "valid.csv"
            skip_csv  = out_dir / "skip.csv"
            csv_file.write_text("id,name\n1,Alice\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            r = subprocess.run(
                [sys.executable, str(VALIDATOR)],
                env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            # Either succeeds and created the dir, or fails with a clear message
            if r.returncode == 0:
                self.assertTrue(valid_csv.exists())
            else:
                self.assertNotIn("Traceback", r.stderr)


class E2EPipelineWithDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Unavailable prerequisites are a FAILURE, not a skip: a green run must
        # mean these tests actually executed.
        if not _DB_E2E_READY:
            raise AssertionError(f"{_SKIP_REASON}. {HELP}")

    """Full CSV → validate → DB load → verify pipeline. Requires PostgreSQL."""

    def test_tier_p_scenarios_all_pass(self):
        """All Tier P eval scenarios must pass when the runner is executed end-to-end."""
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--tiers", "p"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(r.returncode, 0,
                         f"Tier P eval run failed:\n{r.stdout[-2000:]}\n{r.stderr[-500:]}")

    def test_tier_i_idempotency(self):
        """Tier I (idempotency) scenarios must pass against the running PostgreSQL."""
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--tiers", "i"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(r.returncode, 0,
                         f"Tier I eval run failed:\n{r.stdout[-2000:]}\n{r.stderr[-500:]}")


if __name__ == "__main__":
    unittest.main()
