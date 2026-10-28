"""Append-only, hash-chained audit_log (M3a, #107; BR-24, BR-35).

Integration: needs a live PostgreSQL. Fails (never skips) without one.
Runs against a throwaway schema migrated with Alembic, never the live one.
"""

from __future__ import annotations

import threading
import unittest
import uuid
from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config

from api.config import settings
from api.services.audit import acting_as, verify_chain, write_audit

_ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")


def _connect():
    try:
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                                password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)
    except psycopg2.OperationalError as exc:
        raise AssertionError(f"Database unreachable: {exc}") from None


@pytest.mark.integration
class AppendOnlyAudit(unittest.TestCase):
    def setUp(self):
        self.original = settings.UPLOADS_SCHEMA
        settings.UPLOADS_SCHEMA = self.schema = f"audit_test_{uuid.uuid4().hex[:10]}"
        self.cfg = Config(_ALEMBIC_INI)
        self.cfg.attributes["scope"] = "tenant"   # per-tenant tables only; leave the control schema alone
        self.conn = _connect()

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')   # DROP isn't blocked
        self.conn.commit()
        self.conn.close()
        settings.UPLOADS_SCHEMA = self.original

    def _write(self, n: int, actor: str = "alice", conn=None) -> None:
        conn = conn or self.conn
        with conn.cursor() as cur, acting_as(actor):
            for i in range(n):
                write_audit(cur, "upload", i, f"f{i}.csv", f"t{i}", "dynamic", after={"rows": i})
        conn.commit()

    def _verify(self) -> dict:
        with self.conn.cursor() as cur:
            result = verify_chain(cur)
        self.conn.commit()
        return result

    def _sql(self, statement: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(statement.format(t=f'"{self.schema}".audit_log'))

    def test_rows_written_before_the_upgrade_are_chained(self):
        command.upgrade(self.cfg, "0005")
        self._sql("INSERT INTO {t} (action, file_name) VALUES ('upload', 'old1.csv'), ('delete', 'old1.csv')")
        self.conn.commit()
        command.upgrade(self.cfg, "head")
        self._write(2)
        self.assertEqual(self._verify(), {"rows": 4, "intact": True, "firstBadId": None})

    def test_update_delete_and_truncate_are_rejected(self):
        command.upgrade(self.cfg, "head")
        self._write(1)
        for statement in ("UPDATE {t} SET file_name = 'x'", "DELETE FROM {t}", "TRUNCATE {t}"):
            with self.subTest(statement=statement), self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                self._sql(statement)
            self.conn.rollback()
        self.assertEqual(self._verify()["rows"], 1)

    def test_records_actor_tenant_and_values(self):
        command.upgrade(self.cfg, "head")
        self._write(1, actor="bob")
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT actor, tenant_schema, after_value, prev_hash FROM "{self.schema}".audit_log')
            self.assertEqual(cur.fetchone(), ("bob", self.schema, {"rows": 0}, None))

    def test_a_changed_row_breaks_the_chain_at_that_row(self):
        command.upgrade(self.cfg, "head")
        self._write(3)
        self.assertTrue(self._verify()["intact"])
        # The owner can disable a trigger. The chain is what catches that.
        self._sql("ALTER TABLE {t} DISABLE TRIGGER audit_no_change")
        self._sql("UPDATE {t} SET actor = 'mallory' WHERE id = (SELECT id FROM {t} ORDER BY id OFFSET 1 LIMIT 1)")
        self._sql("ALTER TABLE {t} ENABLE TRIGGER audit_no_change")
        self.conn.commit()
        result = self._verify()
        self.assertFalse(result["intact"])
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT id FROM "{self.schema}".audit_log WHERE actor = %s', ("mallory",))
            self.assertEqual(result["firstBadId"], cur.fetchone()[0])

    def test_a_removed_row_breaks_the_chain(self):
        command.upgrade(self.cfg, "head")
        self._write(3)
        self._sql("ALTER TABLE {t} DISABLE TRIGGER audit_no_change")
        self._sql("DELETE FROM {t} WHERE id = (SELECT id FROM {t} ORDER BY id OFFSET 1 LIMIT 1)")
        self._sql("ALTER TABLE {t} ENABLE TRIGGER audit_no_change")
        self.conn.commit()
        self.assertFalse(self._verify()["intact"])

    def test_concurrent_writers_keep_one_unbroken_chain(self):
        command.upgrade(self.cfg, "head")
        errors = []

        def writer(name: str) -> None:
            conn = _connect()
            try:
                for _ in range(15):
                    self._write(1, actor=name, conn=conn)
            except Exception as exc:  # noqa: BLE001 — reported below
                errors.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=writer, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self._verify(), {"rows": 60, "intact": True, "firstBadId": None})

    def test_downgrade_removes_the_triggers_and_columns(self):
        command.upgrade(self.cfg, "head")
        self._write(1)
        command.downgrade(self.cfg, "0005")
        self._sql("UPDATE {t} SET file_name = 'allowed again'")
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = 'audit_log' AND column_name = 'row_hash'",
                        (self.schema,))
            self.assertEqual(cur.fetchone()[0], 0)
