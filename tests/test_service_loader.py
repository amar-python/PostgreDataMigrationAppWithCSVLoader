"""Unit tests for API service loader behavior."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from api.services.dynamic_loader import upload_dynamic
from api.services.te_loader import _cleanup_prior_registry_entries


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
        self.assertTrue(any("DROP TABLE IF EXISTS" in sql_text for sql_text in executed_sql))
        self.assertTrue(any("DELETE FROM" in sql_text for sql_text in executed_sql))
