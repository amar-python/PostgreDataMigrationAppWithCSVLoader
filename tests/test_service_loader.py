"""Unit tests for API service loader behavior."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pytest

from api.services.dynamic_loader import upload_dynamic
from api.services.te_loader import _cleanup_prior_registry_entries

# Without a marker this file is silently excluded from
# `pytest -m "unit or regression or security or snapshot"` — the exact
# command README.md and quality-gate.yml document as the no-DB test run —
# so these tests never actually executed in CI. See GitHub issue filed
# alongside this fix.
pytestmark = pytest.mark.unit


class ServiceLoaderUnitTests(unittest.TestCase):
    def test_dynamic_upload_rejects_mismatched_type_list_length(self):
        content = "col_a,col_b\n1,2\n"
        fake_cursor = MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.__exit__.return_value = None
        fake_cursor.fetchone.return_value = None

        fake_conn = MagicMock()
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = None
        fake_conn.cursor.return_value = fake_cursor

        with patch("api.services.dynamic_loader.Conn", return_value=fake_conn):
            result = upload_dynamic("file.csv", content, ["int8"], overwrite=False)

        self.assertEqual(result["status"], "error")
        self.assertIn("column types", result["message"].lower())

    def test_te_cleanup_prior_registry_entries_drops_dynamic_table(self):
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [
            ("csv_0123456789abcdef", "dynamic"),
            ("te_dev.organisations", "te"),
        ]

        _cleanup_prior_registry_entries(fake_cursor, "file.csv", "hash")

        executed_sql = [str(call.args[0]) for call in fake_cursor.execute.call_args_list]
        drop_stmts = [s for s in executed_sql if "DROP TABLE IF EXISTS" in s]
        self.assertTrue(drop_stmts)
        # Regression guard: the connection's search_path is never set to
        # UPLOADS_SCHEMA, so an unqualified DROP silently misses the table.
        # Must be schema.table, not just table.
        self.assertTrue(
            any("csv_uploads" in s and "csv_0123456789abcdef" in s for s in drop_stmts),
            f"DROP TABLE must be schema-qualified with UPLOADS_SCHEMA; got: {drop_stmts}",
        )
        # Only the dynamic-mode row should be dropped, never the te-mode one.
        self.assertFalse(any("organisations" in s for s in drop_stmts))
        self.assertTrue(any("DELETE FROM" in sql_text for sql_text in executed_sql))
