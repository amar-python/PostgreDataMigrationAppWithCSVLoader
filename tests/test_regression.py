"""Regression tests — pinned tests for previously discovered bug classes.

Each test documents a specific failure mode that was found and fixed.
Adding a test here prevents the same bug from silently re-appearing.
No database required; all tests run offline.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

VALIDATOR = Path(__file__).resolve().parents[1] / "build" / "csv" / "validator.py"


def _run(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class RegressionBomHandling(unittest.TestCase):
    """Validator must accept CSVs with a UTF-8 BOM (byte-order mark).

    BOM-prefixed files are written by Excel on Windows. Previously the
    validator treated the BOM as part of the first column name, causing
    every row to be skipped with 'column mismatch'.
    """

    def test_bom_csv_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "bom_input.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_bytes(b"\xef\xbb\xbfid,name\n1,Alice\n2,Bob\n")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            result = _run(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(lines), 2, "Expected at least header + 1 data row")


class RegressionCrlfLineEndings(unittest.TestCase):
    """Validator must handle Windows CRLF line endings without treating \\r as data.

    Previously CRLF files caused every field in a row to gain a trailing \\r,
    which broke column-count comparisons.
    """

    def test_crlf_csv_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "crlf.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_bytes(b"id,name\r\n1,Alice\r\n2,Bob\r\n")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            result = _run(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(lines), 2)
            # Ensure no trailing \r survived into cell values
            for line in lines:
                self.assertNotIn("\r", line, f"CRLF leaked into valid.csv: {repr(line)}")


class RegressionHeaderOnlyCsv(unittest.TestCase):
    """A CSV with only a header row and no data rows must exit 1 with 'No valid rows found'.

    Previously the validator crashed with an unhandled IndexError when
    iterating over an empty sequence.
    """

    def test_header_only_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "header_only.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_text("id,name\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "people"}
            result = _run(env)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr,
                             "Unhandled exception leaked — must exit cleanly")
            self.assertIn("No valid rows", result.stderr)


class RegressionSingleColumnCsv(unittest.TestCase):
    """Single-column CSVs must be validated correctly.

    Previously a row with a single column was misidentified as 'column mismatch'
    because the comparison logic used len(row) < len(header) rather than !=.
    """

    def test_single_column_valid_rows_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file  = tmp_path / "single_col.csv"
            valid_csv = tmp_path / "valid.csv"
            skip_csv  = tmp_path / "skip.csv"
            csv_file.write_text("name\nAlice\nBob\n", encoding="utf-8")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(valid_csv),
                   "SKIP_FILE":  str(skip_csv),
                   "TABLE_NAME": "names"}
            result = _run(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = valid_csv.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn("Alice", "\n".join(lines))
            self.assertIn("Bob",   "\n".join(lines))


class RegressionNoTraceback(unittest.TestCase):
    """Validator must never emit a raw Python Traceback to stderr on any input.

    Tracebacks expose internal paths and leak implementation details.
    This test exercises several error paths and verifies clean error messages.
    """

    def _assert_no_traceback(self, env: dict, label: str) -> None:
        result = _run(env)
        self.assertNotIn(
            "Traceback",
            result.stderr,
            f"{label}: raw Traceback emitted to stderr — must be caught and reported cleanly",
        )

    def test_missing_env_vars_no_traceback(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CSV_FILE", "VALID_CSV", "SKIP_FILE")}
        self._assert_no_traceback(env, "missing env vars")

    def test_nonexistent_file_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = {**os.environ,
                   "CSV_FILE":   str(tmp_path / "does_not_exist.csv"),
                   "VALID_CSV":  str(tmp_path / "valid.csv"),
                   "SKIP_FILE":  str(tmp_path / "skip.csv"),
                   "TABLE_NAME": "t"}
            self._assert_no_traceback(env, "nonexistent file")

    def test_invalid_utf8_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "bad.csv"
            csv_file.write_bytes(b"id,name\n1,\xe9\n")
            env = {**os.environ,
                   "CSV_FILE":   str(csv_file),
                   "VALID_CSV":  str(tmp_path / "valid.csv"),
                   "SKIP_FILE":  str(tmp_path / "skip.csv"),
                   "TABLE_NAME": "t"}
            self._assert_no_traceback(env, "invalid UTF-8")


if __name__ == "__main__":
    unittest.main()
