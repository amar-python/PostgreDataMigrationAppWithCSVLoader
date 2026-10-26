"""Alembic migrations (#84) and registry uniqueness (#81).

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import unittest
import uuid
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from api.config import settings
from api.db import Conn
from api.main import app
from api.services.dynamic_loader import upload_dynamic
from api.services.te_loader import upload_te

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")
_ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")


def _connect():
    try:
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                                password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)
    except psycopg2.OperationalError as exc:
        raise AssertionError(f"Database unreachable: {exc}\n{_HELP}") from None


def _registry_rows(column: str, value: str) -> int:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{settings.UPLOADS_SCHEMA}".csv_files WHERE {column} = %s', (value,))
        return cur.fetchone()[0]


@pytest.mark.integration
class MigrationsOnScratchSchema(unittest.TestCase):
    """Upgrade and downgrade run against a throwaway schema, never the live one."""

    def setUp(self):
        self.original = (settings.UPLOADS_SCHEMA, settings.CONTROL_SCHEMA)
        tag = uuid.uuid4().hex[:10]
        settings.UPLOADS_SCHEMA = f"mig_test_{tag}"
        settings.CONTROL_SCHEMA = f"mig_ctl_{tag}"   # never touch the live control schema
        self.cfg = Config(_ALEMBIC_INI)
        self.conn = _connect()
        self.conn.autocommit = True

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{settings.UPLOADS_SCHEMA}" CASCADE')
            cur.execute(f'DROP SCHEMA IF EXISTS "{settings.CONTROL_SCHEMA}" CASCADE')
        self.conn.close()
        settings.UPLOADS_SCHEMA, settings.CONTROL_SCHEMA = self.original

    def _constraints(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = %s AND c.contype = 'u'", (settings.UPLOADS_SCHEMA,))
            return {r[0] for r in cur.fetchall()}

    def _tables(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                        (settings.UPLOADS_SCHEMA,))
            return {r[0] for r in cur.fetchall()}

    def test_upgrade_head_creates_tables_and_unique_constraints(self):
        command.upgrade(self.cfg, "head")
        self.assertTrue({"csv_files", "audit_log", "alembic_version"} <= self._tables())
        self.assertEqual(self._constraints(), {"csv_files_file_hash_key", "csv_files_file_name_key"})

    def test_control_schema_is_created_and_removed(self):
        command.upgrade(self.cfg, "head")
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                        (settings.CONTROL_SCHEMA,))
            self.assertEqual({r[0] for r in cur.fetchall()}, {"tenants", "users", "memberships", "sessions"})
        command.downgrade(self.cfg, "0003")
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (settings.CONTROL_SCHEMA,))
            self.assertIsNone(cur.fetchone())

    def test_downgrade_reverses_each_step(self):
        command.upgrade(self.cfg, "head")
        command.downgrade(self.cfg, "0001")
        self.assertEqual(self._constraints(), set())
        self.assertIn("csv_files", self._tables())
        command.downgrade(self.cfg, "base")
        self.assertNotIn("csv_files", self._tables())

    def test_baseline_adopts_a_fallback_created_schema(self):
        # A deployed database created by the old fallback bootstrap already has
        # the tables. Upgrading must adopt them, not fail on CREATE TABLE.
        with self.conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{settings.UPLOADS_SCHEMA}"')
            cur.execute(f'CREATE TABLE "{settings.UPLOADS_SCHEMA}".csv_files (id BIGSERIAL PRIMARY KEY, '
                        "file_name TEXT NOT NULL, file_hash TEXT NOT NULL, table_name TEXT NOT NULL, "
                        "mode TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0, "
                        "column_names TEXT[] NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        command.upgrade(self.cfg, "head")
        self.assertIn("csv_files_file_hash_key", self._constraints())

    def test_existing_duplicates_stop_the_upgrade_with_remediation(self):
        command.upgrade(self.cfg, "0001")
        with self.conn.cursor() as cur:
            for name in ("a.csv", "b.csv"):
                cur.execute(f'INSERT INTO "{settings.UPLOADS_SCHEMA}".csv_files '
                            "(file_name, file_hash, table_name, mode) VALUES (%s, 'samehash', 't', 'dynamic')",
                            (name,))
        with self.assertRaisesRegex(RuntimeError, "duplicated value.*samehash"):
            command.upgrade(self.cfg, "head")
        self.assertEqual(self._constraints(), set())


@pytest.mark.integration
class RegistryUniqueness(unittest.TestCase):
    """The live uploads schema, brought to head by the API's own bootstrap."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def test_bootstrap_brings_the_schema_to_head(self):
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(f'SELECT version_num FROM "{settings.UPLOADS_SCHEMA}".alembic_version')
            self.assertEqual(cur.fetchone()[0], "0005")

    def test_duplicate_hash_is_rejected_by_the_database(self):
        insert = (f'INSERT INTO "{settings.UPLOADS_SCHEMA}".csv_files (file_name, file_hash, table_name, mode) '
                  "VALUES (%s, %s, 't', 'dynamic')")
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(insert, (f"a_{self.tag}.csv", f"h_{self.tag}"))
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                cur.execute(insert, (f"b_{self.tag}.csv", f"h_{self.tag}"))
            conn.rollback()

    def _against_uncommitted_competitor(self, fn, name: str, content: str, table: str, mode: str) -> dict:
        """Run fn while another transaction holds an uncommitted registry row for
        the same file. fn's own duplicate check cannot see that row, so it gets as
        far as registering and blocks on the UNIQUE index; committing the
        competitor then forces the race outcome deterministically."""
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        competitor = _connect()
        result: dict = {}
        try:
            with competitor.cursor() as cur:
                cur.execute(f'INSERT INTO "{settings.UPLOADS_SCHEMA}".csv_files '
                            "(file_name, file_hash, table_name, mode) VALUES (%s, %s, %s, %s)",
                            (name, file_hash, table, mode))
            worker = threading.Thread(target=lambda: result.update(fn()))
            worker.start()
            watcher = _connect()
            watcher.autocommit = True
            try:
                for _ in range(200):  # up to 10 s for the worker to block on the index
                    with watcher.cursor() as cur:
                        cur.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
                        if cur.fetchone()[0]:
                            break
                    time.sleep(0.05)
                else:
                    raise AssertionError("worker never blocked on the registry's UNIQUE index")
            finally:
                watcher.close()
            competitor.commit()
            worker.join(timeout=60)
            return result
        finally:
            with competitor.cursor() as cur:
                cur.execute(f'DELETE FROM "{settings.UPLOADS_SCHEMA}".csv_files WHERE file_name = %s', (name,))
            competitor.commit()
            competitor.close()

    def test_dynamic_upload_losing_the_race_reports_duplicate_and_commits_nothing(self):
        name = f"race_{self.tag}.csv"
        content = f"a,b\n1,{self.tag}\n2,{self.tag}\n"
        table = f"csv_{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        result = self._against_uncommitted_competitor(
            lambda: upload_dynamic(name, content, None, False), name, content, table, "dynamic")
        self.assertEqual(result["status"], "duplicate_file")
        with Conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f'"{settings.UPLOADS_SCHEMA}".{table}',))
            self.assertIsNone(cur.fetchone()[0], "the losing upload's table must be rolled back")

    def test_te_load_losing_the_race_reports_error_and_rolls_back_rows(self):
        name = f"race_te_{self.tag}.csv"
        content = "name,org_type,country\n" + "\n".join(
            f"RACE_{self.tag}_{i},government,AU" for i in range(20)) + "\n"
        result = self._against_uncommitted_competitor(
            lambda: upload_te(name, content, "organisations"), name, content,
            f"{settings.TE_SCHEMA}.organisations", "te")
        self.assertEqual(result["status"], "error")
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{settings.TE_SCHEMA}".organisations WHERE name LIKE %s',
                        (f"RACE_{self.tag}_%",))
            self.assertEqual(cur.fetchone()[0], 0, "the losing load must roll back its rows")
