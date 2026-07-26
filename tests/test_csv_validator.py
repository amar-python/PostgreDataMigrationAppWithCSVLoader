"""Tests for build/csv/validator.py.

Runs the validator as a subprocess via environment-variable injection
(CSV_FILE, VALID_CSV, SKIP_FILE). No database required; all tests are
self-contained using tempfile directories.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class CsvValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = Path(__file__).resolve().parents[1] / "build" / "csv" / "validator.py"

    def run_validator(self, env):
        result = subprocess.run(
            [sys.executable, str(self.validator)],
            env=env,
            capture_output=True,
            text=True,
        )
        return result

    def test_fails_when_required_env_vars_missing(self):
        """When CSV_FILE/VALID_CSV/SKIP_FILE are absent, the validator should exit 1 with 'Missing required environment variables' on stderr."""
        env = os.environ.copy()
        env.pop("CSV_FILE", None)
        env.pop("VALID_CSV", None)
        env.pop("SKIP_FILE", None)
        result = self.run_validator(env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing required environment variables", result.stderr)

    def test_fails_when_csv_file_missing(self):
        """When CSV_FILE points to a non-existent path, the validator should exit 1 with 'CSV file not found' on stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = os.environ.copy()
            env["CSV_FILE"] = str(tmp_path / "missing.csv")
            env["VALID_CSV"] = str(tmp_path / "out" / "valid.csv")
            env["SKIP_FILE"] = str(tmp_path / "out" / "skip.csv")
            result = self.run_validator(env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("CSV file not found", result.stderr)

    def test_splits_valid_and_skipped_rows(self):
        """Given a 4-row CSV (2 valid, 1 empty row, 1 column-mismatch), valid.csv gets the 2 good rows and skip.csv gets 2 annotated rows with a _skip_reason column."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "input.csv"
            valid_csv = tmp_path / "out" / "valid.csv"
            skip_csv = tmp_path / "out" / "skip.csv"
            csv_file.write_text(
                "id,name\n1,Alice\n\n2\n3,Bob\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["CSV_FILE"] = str(csv_file)
            env["VALID_CSV"] = str(valid_csv)
            env["SKIP_FILE"] = str(skip_csv)
            env["TABLE_NAME"] = "people"
            result = self.run_validator(env)
            self.assertEqual(result.returncode, 0)
            valid_lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            skip_lines = skip_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(valid_lines, ["id,name", "1,Alice", "3,Bob"])
            self.assertEqual(len(skip_lines), 3)
            self.assertTrue(skip_lines[0].endswith("_skip_reason"))
            self.assertIn("empty row", skip_lines[1])
            self.assertIn("column mismatch", skip_lines[2])

    def test_returns_error_when_no_valid_rows(self):
        """When all data rows are invalid, the validator should exit 1 with 'No valid rows found' on stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "input.csv"
            valid_csv = tmp_path / "out" / "valid.csv"
            skip_csv = tmp_path / "out" / "skip.csv"
            csv_file.write_text("id,name\n\n2\n", encoding="utf-8")
            env = os.environ.copy()
            env["CSV_FILE"] = str(csv_file)
            env["VALID_CSV"] = str(valid_csv)
            env["SKIP_FILE"] = str(skip_csv)
            result = self.run_validator(env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("No valid rows found", result.stderr)


if __name__ == "__main__":
    unittest.main()
