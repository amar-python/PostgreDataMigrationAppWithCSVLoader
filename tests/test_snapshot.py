"""Snapshot (golden-file) tests — compare validator output against stored expected files.

On first run, or when UPDATE_SNAPSHOTS=1 is set, the test writes the golden
file. On subsequent runs it compares the actual output against the stored file
and fails if they differ.

    UPDATE_SNAPSHOTS=1 pytest -m snapshot tests/test_snapshot.py   # regenerate
    pytest -m snapshot tests/test_snapshot.py                       # compare
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.snapshot]

VALIDATOR     = Path(__file__).resolve().parents[1] / "build" / "csv" / "validator.py"
SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"
UPDATE        = os.environ.get("UPDATE_SNAPSHOTS", "").lower() in ("1", "true", "yes")


def _run_validator(csv_content: bytes, table_name: str = "people") -> tuple[str, str, int]:
    """Run the validator on csv_content bytes; return (valid_text, skip_text, exit_code)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_file  = tmp_path / "input.csv"
        valid_csv = tmp_path / "valid.csv"
        skip_csv  = tmp_path / "skip.csv"
        csv_file.write_bytes(csv_content)
        env = {
            **os.environ,
            "CSV_FILE":   str(csv_file),
            "VALID_CSV":  str(valid_csv),
            "SKIP_FILE":  str(skip_csv),
            "TABLE_NAME": table_name,
        }
        r = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        valid_text = valid_csv.read_text(encoding="utf-8") if valid_csv.exists() else ""
        skip_text  = skip_csv.read_text(encoding="utf-8")  if skip_csv.exists()  else ""
        return valid_text, skip_text, r.returncode


def _assert_snapshot(actual: str, snap_name: str) -> None:
    snap_path = SNAPSHOTS_DIR / snap_name
    if UPDATE or not snap_path.exists():
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(actual, encoding="utf-8")
        return
    expected = snap_path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"Snapshot mismatch for {snap_name!r}.\n"
        f"Run with UPDATE_SNAPSHOTS=1 to regenerate.\n"
        f"--- expected ---\n{expected}\n"
        f"--- actual ---\n{actual}"
    )


class SnapshotBasicMixedInput(unittest.TestCase):
    """Golden-file test for a CSV with valid rows, an empty row, and a column mismatch."""

    def test_valid_csv_matches_snapshot(self):
        csv_file = SNAPSHOTS_DIR / "basic_input.csv"
        self.assertTrue(csv_file.exists(), f"Snapshot input missing: {csv_file}")
        content = csv_file.read_bytes()
        valid_text, _, exit_code = _run_validator(content)
        self.assertEqual(exit_code, 0)
        _assert_snapshot(valid_text, "basic_expected_valid.csv")

    def test_skip_csv_matches_snapshot(self):
        csv_file = SNAPSHOTS_DIR / "basic_input.csv"
        self.assertTrue(csv_file.exists(), f"Snapshot input missing: {csv_file}")
        content = csv_file.read_bytes()
        _, skip_text, exit_code = _run_validator(content)
        self.assertEqual(exit_code, 0)
        _assert_snapshot(skip_text, "basic_expected_skip.csv")


class SnapshotAllValidInput(unittest.TestCase):
    """Golden-file test for a CSV where every row is valid — skip.csv should be empty."""

    def test_all_valid_no_skips(self):
        content = b"id,name\n1,Alice\n2,Bob\n3,Carol\n"
        valid_text, skip_text, exit_code = _run_validator(content)
        self.assertEqual(exit_code, 0)
        _assert_snapshot(valid_text, "all_valid_expected_valid.csv")
        # skip file should have only a header (or be empty)
        skip_lines = [l for l in skip_text.splitlines() if l.strip()]
        self.assertLessEqual(len(skip_lines), 1,
                             "Expected at most a header row in skip.csv when all rows are valid")


if __name__ == "__main__":
    unittest.main()
