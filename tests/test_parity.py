"""Cross-environment parity tests — row-count and schema consistency.

Mirrors gstack's parity-suite.test.ts and parity-baseline-integrity.test.ts:
asserts that seeded environments contain the expected number of rows, that
all expected tables exist, and that counts don't drift between identical
deployments.

All tests skip automatically when PostgreSQL is not reachable.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.parity]

ROOT = Path(__file__).resolve().parents[1]

# Expected minimum seed row counts for the dev environment (from seed data).
# Adjust these values if the seed SQL is intentionally changed.
_DEV_MIN_COUNTS: dict[str, int] = {
    "organisations": 1,
    "personnel":     1,
    "test_programs": 1,
    "test_phases":   1,
    "requirements":  1,
    "test_cases":    1,
    "vcrm_entries":  1,
    "test_events":   1,
    "test_results":  1,
    "defect_reports": 1,
}

# Tables that must exist in every environment (not just dev)
_REQUIRED_TABLES = [
    "organisations", "personnel", "test_programs", "temp_documents",
    "test_phases", "requirements", "test_cases", "vcrm_entries",
    "test_events", "test_results", "defect_reports", "evidence_artifacts",
]

_ENV_CONFIG = {
    "dev":     ("te_mgmt_dev",     "te_dev"),
    "test":    ("te_mgmt_test",    "te_test"),
    "staging": ("te_mgmt_staging", "te_staging"),
    "prod":    ("te_mgmt_prod",    "te_prod"),
}


def _pg_env() -> dict:
    env = os.environ.copy()
    env.setdefault("PGUSER", "postgres")
    return env


def _have_psql() -> bool:
    return shutil.which("psql") is not None


def _can_connect() -> bool:
    if not _have_psql():
        return False
    try:
        r = subprocess.run(
            ["psql", "-tA", "-c", "SELECT 1"],
            env=_pg_env(), capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _count_rows(db: str, schema: str, table: str) -> int | None:
    query = f'SELECT count(*) FROM {schema}."{table}";'
    r = subprocess.run(
        ["psql", "-tA", "-d", db, "-c", query],
        env=_pg_env(), capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return int(r.stdout.strip())
    return None


def _table_exists(db: str, schema: str, table: str) -> bool:
    query = (
        f"SELECT 1 FROM information_schema.tables "
        f"WHERE table_schema='{schema}' AND table_name='{table}';"
    )
    r = subprocess.run(
        ["psql", "-tA", "-d", db, "-c", query],
        env=_pg_env(), capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


def _db_deployed(db: str) -> bool:
    """True only if the environment database actually exists on the server."""
    if not _can_connect():
        return False
    try:
        r = subprocess.run(
            ["psql", "-tA", "-c",
             f"SELECT 1 FROM pg_database WHERE datname = '{db}'"],
            env=_pg_env(), capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "1"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


_PG_AVAILABLE = _can_connect()
# Reachable server is not enough — parity tests read seeded rows, so the
# environment must also have been deployed (deploy_all.sh). A fresh clone has
# a running server but no te_mgmt_* databases; skip rather than fail.
_DEV_DEPLOYED = _db_deployed(_ENV_CONFIG["dev"][0])
_HELP = ("Run 'bash scripts/provision_full_test_env.sh' (needs a reachable "
         "PostgreSQL and PGUSER/PGHOST/PGPORT set).")


def _require_pg():
    """Unavailable prerequisites FAIL — a green run must mean these ran."""
    if not _PG_AVAILABLE:
        raise AssertionError(f"PostgreSQL not reachable. {_HELP}")


def _require_deployed():
    _require_pg()
    if not _DEV_DEPLOYED:
        raise AssertionError(f"Dev database not deployed. {_HELP}")


class TestDevSeedCounts(unittest.TestCase):
    setUpClass = classmethod(lambda cls: _require_deployed())
    """Dev environment must contain at least the expected seed row counts."""

    def test_dev_seed_row_counts(self):
        db, schema = _ENV_CONFIG["dev"]
        failures = []
        for table, min_count in _DEV_MIN_COUNTS.items():
            count = _count_rows(db, schema, table)
            if count is None:
                failures.append(f"  {schema}.{table}: could not query (table may not exist)")
            elif count < min_count:
                failures.append(
                    f"  {schema}.{table}: expected >= {min_count} rows, got {count}"
                )
        if failures:
            self.fail("Dev seed row count failures:\n" + "\n".join(failures))


class TestAllEnvironmentsHaveRequiredTables(unittest.TestCase):
    setUpClass = classmethod(lambda cls: _require_pg())
    """Every deployed environment must contain all required tables."""

    def _check_env(self, env_name: str) -> None:
        db, schema = _ENV_CONFIG[env_name]
        # Skip if this database doesn't exist at all
        r = subprocess.run(
            ["psql", "-tA", "-d", db, "-c", "SELECT 1"],
            env=_pg_env(), capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            self.fail(f"Database {db!r} not deployed. {_HELP}")

        missing = [
            t for t in _REQUIRED_TABLES
            if not _table_exists(db, schema, t)
        ]
        if missing:
            self.fail(
                f"Environment {env_name!r} ({db}/{schema}) is missing tables:\n"
                + "\n".join(f"  {t}" for t in missing)
            )

    def test_dev_has_required_tables(self):
        self._check_env("dev")

    def test_test_has_required_tables(self):
        self._check_env("test")

    def test_staging_has_required_tables(self):
        self._check_env("staging")

    def test_prod_has_required_tables(self):
        self._check_env("prod")


class TestIdempotentDeployParity(unittest.TestCase):
    setUpClass = classmethod(lambda cls: _require_pg())
    """Row counts in dev must be identical after re-running the deploy script.

    This is the parity equivalent of gstack's parity-baseline-integrity test:
    a second deploy must produce identical counts, not duplicates or deletions.
    """

    def test_dev_row_counts_stable_after_second_deploy(self):
        env_sql = ROOT / "build" / "environments" / "env_dev.sql"
        if not env_sql.exists():
            self.fail(f"env_dev.sql not found at {env_sql}. {_HELP}")

        db, schema = _ENV_CONFIG["dev"]

        def _snapshot() -> dict[str, int | None]:
            return {t: _count_rows(db, schema, t) for t in _REQUIRED_TABLES}

        counts_before = _snapshot()

        r = subprocess.run(
            ["psql", "-f", str(env_sql)],
            env=_pg_env(), capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            self.fail(f"Second deploy failed:\n{r.stderr[-500:]}")

        counts_after = _snapshot()

        drifted = {
            t: (counts_before.get(t), counts_after.get(t))
            for t in _REQUIRED_TABLES
            if counts_before.get(t) != counts_after.get(t)
        }
        if drifted:
            lines = [f"  {t}: {before} → {after}" for t, (before, after) in drifted.items()]
            self.fail("Row counts drifted after idempotent re-deploy:\n" + "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
