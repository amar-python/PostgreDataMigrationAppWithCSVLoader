"""Tests for build/csv_utilise.sh.

Argument-parsing and reachability paths are covered as unit tests (no DB).
Database-backed paths (list/describe/peek/export/drop against a real schema)
live alongside the integration tests in test_csv_loader_arbitrary_shapes.py.
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[1] / "build" / "csv_utilise.sh"


def _find_bash():
    """Locate a real bash. On Windows, PATH-resolved `bash` is often WSL
    (which may have no distro installed); prefer Git Bash explicitly.
    Returns the absolute path, or None if no working bash is found."""
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        # Last resort: PATH lookup, but skip wsl shims.
        which = shutil.which("bash")
        if which and "system32" not in which.lower():
            return which
        return None
    return shutil.which("bash") or "bash"


_BASH = _find_bash()


def run(args, env=None):
    """Run csv_utilise.sh with the given args; capture output."""
    return subprocess.run(
        [_BASH, str(SCRIPT), *args],
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


class CsvUtiliseArgumentParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if _BASH is None:
            raise AssertionError(
                "No working bash found — install Git Bash and ensure it is on PATH.")

    def test_no_args_shows_usage_and_exits_nonzero(self):
        """No args → exit 1 with usage banner on stdout."""
        r = run([])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Usage:", r.stdout)

    def test_unknown_command_exits_nonzero(self):
        """Unknown subcommand → exit 1 with 'Unknown command' on stderr."""
        r = run(["frobnicate"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown command", r.stderr)

    def test_describe_requires_table_arg(self):
        """`describe` with no positional table → exit 1 with a helpful message."""
        r = run(["describe"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a <table> argument", r.stderr)

    def test_peek_requires_table_arg(self):
        """`peek` with no positional table → exit 1 with a helpful message."""
        r = run(["peek"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a <table> argument", r.stderr)

    def test_export_requires_two_positional_args(self):
        """`export` needs both <table> and <out.csv> → exit 1 otherwise."""
        r = run(["export", "only_one"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires <table> and <out.csv>", r.stderr)

    def test_drop_requires_table_arg(self):
        """`drop` with no positional table → exit 1."""
        r = run(["drop"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a <table> argument", r.stderr)

    def test_help_flag_exits_zero(self):
        """`--help` short-circuits to a 0 exit with the usage banner."""
        r = run(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)

    def test_invalid_table_name_rejected(self):
        """Identifier validation rejects names with spaces or punctuation."""
        # Use --engine postgresql so we get past engine validation; the
        # identifier check happens before any DB connection.
        r = run(["describe", "bad name; DROP TABLE x", "--engine", "postgresql"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Invalid table name", r.stderr)

    def test_unimplemented_engine_returns_clear_error(self):
        """Engines other than postgresql exit 2 with a 'not implemented' message."""
        r = run(["list", "--engine", "redis"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("not implemented", r.stderr)


if __name__ == "__main__":
    unittest.main()
