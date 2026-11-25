"""Shared pytest fixtures.

Tests are split into two tiers:

* Unit tests work on the CSV side only and need no database. They use the
  config and sample data shipped with the framework.
* Integration tests require a running PostgreSQL. They are gated behind the
  `integration` marker. To skip them: `pytest -m "not integration"`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `src` importable regardless of where pytest is run from.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import JobConfig, load_db_config, load_jobs  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def config_path(repo_root: Path) -> Path:
    return repo_root / "config.yaml"


@pytest.fixture(scope="session")
def jobs(config_path: Path):
    # BUG-13: load_jobs now resolves relative paths against the config
    # file's directory, so we no longer need to chdir into the repo root.
    return load_jobs(config_path)


@pytest.fixture(scope="session")
def users_job(jobs) -> JobConfig:
    for j in jobs:
        if j.name == "users":
            return j
    pytest.fail("users job not in config.yaml")


# ----------------------------- DB fixtures -----------------------------------

def _can_connect() -> bool:
    """Cheap probe so we can skip the integration suite if no DB is available."""
    try:
        import psycopg2
    except ImportError:
        return False
    try:
        cfg = load_db_config()
        with psycopg2.connect(connect_timeout=2, **cfg.connect_kwargs()):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    return _can_connect()


@pytest.fixture
def pg_conn(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not reachable; set PG_* env vars and start the DB")
    import psycopg2
    cfg = load_db_config()
    conn = psycopg2.connect(**cfg.connect_kwargs())
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        conn.close()


@pytest.fixture
def fresh_target_table(pg_conn, users_job, repo_root):
    """Drop and recreate the target table from the schema file.

    BUG-12: rollback before cleanup so a previous test that aborted its
    transaction doesn't poison the teardown with
    'current transaction is aborted'.
    """
    schema_sql = Path(users_job.schema_file).read_text(encoding="utf-8")
    pg_conn.rollback()
    with pg_conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{users_job.staging_table}" CASCADE')
        cur.execute(f'DROP TABLE IF EXISTS "{users_job.target_table}" CASCADE')
        cur.execute(schema_sql)
    pg_conn.commit()
    yield
    # Always rollback before destructive teardown so an aborted in-test
    # transaction doesn't break cleanup.
    pg_conn.rollback()
    with pg_conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{users_job.staging_table}" CASCADE')
        cur.execute(f'DROP TABLE IF EXISTS "{users_job.target_table}" CASCADE')
    pg_conn.commit()
