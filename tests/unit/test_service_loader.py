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

    def test_te_cleanup_prior_registry_entries_never_drops_a_table(self):
        """#287, BR-51: a T&E upload never drops a dynamic dataset.

        This test used to assert the opposite (that the cleanup DROPs the dynamic table, schema-qualified). That
        was the defect: uploading the same bytes in T&E mode destroyed a versioned dataset with the destructive
        flag off. The cleanup now only deletes T&E registry rows and drops nothing. The fixture still holds a
        dynamic row, so the old behaviour (drop it) fails here rather than passing vacuously.
        """
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [
            ("csv_0123456789abcdef", "dynamic"),
            ("te_dev.organisations", "te"),
        ]

        _cleanup_prior_registry_entries(fake_cursor, "file.csv", "hash")

        executed_sql = [str(call.args[0]) for call in fake_cursor.execute.call_args_list]
        self.assertFalse(
            any("DROP" in s.upper() for s in executed_sql),
            f"the T&E cleanup must not drop any table; got: {executed_sql}",
        )
        deletes = [s for s in executed_sql if "DELETE FROM" in s]
        self.assertEqual(len(deletes), 1, f"expected one registry DELETE; got: {executed_sql}")
        # The only rows it may remove are T&E ones: the DELETE excludes dynamic mode.
        self.assertIn("mode <>", deletes[0])
        self.assertIn("dynamic", deletes[0])
