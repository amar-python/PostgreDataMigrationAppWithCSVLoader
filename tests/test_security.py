"""Security scan tests — static analysis over project source files.

Mirrors the role of gstack's redact-*.test.ts suite: catches hardcoded
credentials, plaintext secrets, and unsafe SQL patterns before they reach
the repository or production.

No database required; all tests are purely static (file-read) checks.
"""
import re
import unittest
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[1]

# ── Python source files to scan ───────────────────────────────────────────────
PY_SOURCE = [
    ROOT / "build" / "csv" / "validator.py",
    ROOT / "evals" / "runner.py",
    ROOT / "evals" / "gap_report.py",
]

# ── Shell scripts to scan ─────────────────────────────────────────────────────
SHELL_SCRIPTS = list((ROOT / "build" / "adapters").glob("adapter_*.sh")) + \
                list((ROOT / "build" / "csv").glob("loader_*.sh")) + [
                    ROOT / "build" / "deploy_all.sh",
                    ROOT / "build" / "setup.sh",
                    ROOT / "build" / "csv_loader.sh",
                ]

# ── Patterns that must NOT appear in source ───────────────────────────────────
# Matches a password-like variable assigned a non-empty literal value
_HARDCODED_PASSWORD = re.compile(
    r'(?i)(password|passwd|secret|pg_password)\s*[=:]\s*["\'][^"\']{3,}["\']'
)

# f-string containing what looks like a SQL keyword — SQL must never be built
# with f-strings; use psycopg2.sql.Identifier / parameterised queries.
_FSTRING_SQL = re.compile(
    r'f["\'].*\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b.*["\']',
    re.IGNORECASE,
)


class TestNoHardcodedCredentials(unittest.TestCase):
    """Python source files must not contain hardcoded passwords or secrets."""

    def _scan(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if _HARDCODED_PASSWORD.search(line):
                self.fail(
                    f"Possible hardcoded credential in {path.relative_to(ROOT)}:{i}\n"
                    f"  {line.strip()}\n"
                    "Remove or move to environment variable / config file."
                )

    def test_validator_no_hardcoded_credentials(self):
        self._scan(ROOT / "build" / "csv" / "validator.py")

    def test_runner_no_hardcoded_credentials(self):
        self._scan(ROOT / "evals" / "runner.py")

    def test_gap_report_no_hardcoded_credentials(self):
        self._scan(ROOT / "evals" / "gap_report.py")


class TestNoFStringSql(unittest.TestCase):
    """Python source must not use f-strings to build SQL statements.

    All SQL must use psycopg2.sql.Identifier() or parameterised queries
    to prevent SQL injection. (See CLAUDE.md project guideline.)
    """

    def _scan(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if _FSTRING_SQL.search(line):
                self.fail(
                    f"f-string SQL detected in {path.relative_to(ROOT)}:{i}\n"
                    f"  {line.strip()}\n"
                    "Use psycopg2.sql.Identifier() or parameterised queries instead."
                )

    def test_validator_no_fstring_sql(self):
        self._scan(ROOT / "build" / "csv" / "validator.py")

    def test_runner_no_fstring_sql(self):
        self._scan(ROOT / "evals" / "runner.py")


class TestConfigEnvExample(unittest.TestCase):
    """config.env.example must have an empty PG_PASSWORD (safe default)."""

    def test_pg_password_is_empty(self):
        example = ROOT / "build" / "config.env.example"
        self.assertTrue(example.exists(), f"config.env.example not found at {example}")
        text = example.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("PG_PASSWORD"):
                # Acceptable: PG_PASSWORD=""  or  PG_PASSWORD=''  or  PG_PASSWORD=
                self.assertRegex(
                    stripped,
                    r'^PG_PASSWORD\s*=\s*(["\'][\s]*["\']|)(\s*#.*)?$',
                    "PG_PASSWORD in config.env.example must be empty — "
                    "do not commit real credentials.",
                )
                return
        # If PG_PASSWORD line is absent entirely that is also fine
        pass


class TestShellScriptsNoPrintedPasswords(unittest.TestCase):
    """Shell scripts must not echo password values.

    `echo $PGPASSWORD` or `echo $PG_PASSWORD` in a script would expose the
    credential in CI logs.
    """

    _ECHO_PASSWORD = re.compile(
        r'\becho\b.*\$(PG_?PASSWORD|PGPASSWORD)',
        re.IGNORECASE,
    )

    def test_no_echo_password_in_adapters(self):
        for script in (ROOT / "build" / "adapters").glob("adapter_*.sh"):
            text = script.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if self._ECHO_PASSWORD.search(line) and not line.strip().startswith("#"):
                    self.fail(
                        f"Password may be echoed to stdout in "
                        f"{script.relative_to(ROOT)}:{i}:\n  {line.strip()}"
                    )

    def test_no_echo_password_in_loaders(self):
        for script in (ROOT / "build" / "csv").glob("loader_*.sh"):
            text = script.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if self._ECHO_PASSWORD.search(line) and not line.strip().startswith("#"):
                    self.fail(
                        f"Password may be echoed to stdout in "
                        f"{script.relative_to(ROOT)}:{i}:\n  {line.strip()}"
                    )


class TestSqlFilesNoInlineCredentials(unittest.TestCase):
    """SQL environment files must not contain inline password literals."""

    _SQL_PASSWORD = re.compile(
        r"(?i)(PASSWORD\s+['\"][^'\"]{3,}['\"])",
    )
    # Obvious placeholder values are allowed in committed template files
    # (e.g. env_dev.example.sql). Real secrets never match these shapes.
    _PLACEHOLDER = re.compile(
        r"(?i)['\"](__[A-Z0-9_]+__|CHANGE_?ME\w*|YOUR_[A-Z0-9_]+|PLACEHOLDER\w*)['\"]",
    )

    def test_env_sql_files_no_hardcoded_passwords(self):
        env_dir = ROOT / "build" / "environments"
        for sql_file in env_dir.glob("env_*.sql"):
            text = sql_file.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if self._PLACEHOLDER.search(line):
                    continue
                if self._SQL_PASSWORD.search(line) and not line.strip().startswith("--"):
                    self.fail(
                        f"Possible hardcoded password in SQL file "
                        f"{sql_file.relative_to(ROOT)}:{i}:\n  {line.strip()}"
                    )


if __name__ == "__main__":
    unittest.main()
