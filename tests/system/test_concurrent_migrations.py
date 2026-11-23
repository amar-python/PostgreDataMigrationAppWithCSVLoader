"""#286 (OIT-001, BR-50): migrations run at API start must be safe when processes start together.

Every API process runs ``alembic upgrade head`` in ``bootstrap()``. Reproduction R1 of the 2026-11-20
review: two processes upgrading a fresh schema at the same moment, one failed in 5 of 5 trials
(``UniqueViolation`` on ``CREATE SCHEMA`` / ``alembic_version``), which aborts that API's start-up.

Each trial starts two separate Python processes (Alembic's context is process-global, so threads would
not show the race) that import everything first, then wait for a shared start time and upgrade the same
scratch schemas. Asserted: both exit 0 and ``alembic_version`` is head, 10 of 10 trials, on a fresh
schema and on one a revision behind. Needs a live PostgreSQL, as in CI.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

import psycopg2
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from api.config import settings

ROOT = Path(__file__).resolve().parents[2]
INI = str(ROOT / "alembic.ini")
TRIALS = 10

# Imports first, then wait for the shared start time, so both processes reach Alembic together.
_WORKER = """
import os, sys, time
from alembic import command
from alembic.config import Config
from api.config import settings  # noqa: F401  (reads CSV_UPLOADS_SCHEMA / CONTROL_SCHEMA)
target, start_at = sys.argv[1], float(sys.argv[2])
cfg = Config(os.environ["ALEMBIC_INI"])
time.sleep(max(0.0, start_at - time.time()))
command.upgrade(cfg, target)
"""

HEAD = ScriptDirectory.from_config(Config(INI)).get_current_head()
ONE_BEHIND = ScriptDirectory.from_config(Config(INI)).get_revision(HEAD).down_revision


def _error_line(result: subprocess.CompletedProcess) -> str:
    """The exception line from a worker's traceback, not SQLAlchemy's trailing background link."""
    lines = [ln for ln in result.stderr.splitlines() if "Error" in ln and not ln.startswith("(Background")]
    return lines[-1][:300] if lines else f"exit {result.returncode}"


def _connect():
    return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                            password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)


@pytest.mark.integration
class ConcurrentStartupMigrations(unittest.TestCase):

    def setUp(self):
        tag = uuid.uuid4().hex[:10]
        self.uploads, self.control = f"mig_cc_{tag}", f"mig_ccc_{tag}"
        self.env = {**os.environ, "CSV_UPLOADS_SCHEMA": self.uploads, "CONTROL_SCHEMA": self.control,
                    "ALEMBIC_INI": INI, "PYTHONPATH": str(ROOT)}
        self.conn = _connect()
        self.conn.autocommit = True

    def tearDown(self):
        self._drop()
        self.conn.close()

    def _drop(self):
        with self.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{self.uploads}" CASCADE')
            cur.execute(f'DROP SCHEMA IF EXISTS "{self.control}" CASCADE')

    def _run(self, target: str, n: int) -> list[subprocess.CompletedProcess]:
        start_at = f"{time.time() + 2.0:.3f}"
        procs = [subprocess.Popen([sys.executable, "-c", _WORKER, target, start_at], cwd=ROOT, env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(n)]
        out = []
        for p in procs:
            stdout, stderr = p.communicate(timeout=120)
            out.append(subprocess.CompletedProcess(p.args, p.returncode, stdout, stderr))
        return out

    def _version(self) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f'"{self.uploads}".alembic_version',))
            if cur.fetchone()[0] is None:
                return None
            cur.execute(f'SELECT version_num FROM "{self.uploads}".alembic_version')
            return cur.fetchone()[0]

    def _trials(self, *, behind: bool) -> None:
        failures = []
        for trial in range(1, TRIALS + 1):
            self._drop()
            if behind:
                prep = self._run(ONE_BEHIND, 1)[0]
                self.assertEqual(prep.returncode, 0, prep.stderr[-2000:])
            results = self._run("head", 2)
            bad = [_error_line(r) for r in results if r.returncode != 0]
            if bad or self._version() != HEAD:
                failures.append(f"trial {trial}: {bad or 'version ' + str(self._version())}")
        self.maxDiff = None
        self.assertEqual(failures, [], f"{len(failures)} of {TRIALS} trials failed")

    def test_two_processes_upgrading_a_fresh_schema_both_start(self):
        self._trials(behind=False)

    def test_two_processes_upgrading_a_schema_one_revision_behind_both_start(self):
        self._trials(behind=True)
