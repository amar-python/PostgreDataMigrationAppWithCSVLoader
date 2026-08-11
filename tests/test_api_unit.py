"""API unit tests — no database required.
Database-backed tests live in test_api_integration.py.
"""
from __future__ import annotations

import unittest

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

_HELP = ("Start PostgreSQL and ensure api/ can reach it. Most often this means "
         "PGPASSWORD is not set in this shell:\n"
         "    PowerShell:  $env:PGPASSWORD = '<password>'\n"
         "    bash:        export PGPASSWORD='<password>'\n"
         "Defaults come from api/config.py; see scripts/start-api.ps1.")

SMALL_CSV = "col_a,col_b\n1,2\n3,4\n"


def _db_reachable() -> bool:
    """The API's own health endpoint is the authority on DB reachability."""
    try:
        return client.get("/api/health").json().get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.unit
class UnitCsvParse(unittest.TestCase):
    """Pure-function tests for api.services.csv_parse — no DB, no TestClient."""

    def test_sanitize_columns_no_collision_on_stem_conflict(self):
        """BUG-036 regression: ["foo","foo","foo_2"] must produce three
        distinct names. The old algorithm bumped a per-stem counter without
        checking the resulting name against already-assigned names, so the
        second "foo" became "foo_2" and collided with the caller-supplied
        "foo_2" — the dynamic loader then rejected the whole upload as
        "Duplicate sanitized column".
        """
        from api.services.csv_parse import sanitize_columns

        out = sanitize_columns(["foo", "foo", "foo_2"])
        self.assertEqual(len(out), len(set(out)),
                         f"BUG-036 regression: collision in {out}")
        # First occurrence keeps its name; later ones get bumped past
        # anything already assigned.
        self.assertEqual(out[0], "foo")

    def test_sanitize_columns_dedupes_true_duplicates(self):
        """Guard-rail for the BUG-036 fix: real duplicate stems still dedupe."""
        from api.services.csv_parse import sanitize_columns

        out = sanitize_columns(["name", "name", "name"])
        self.assertEqual(len(out), 3)
        self.assertEqual(len(set(out)), 3)
        self.assertEqual(out[0], "name")

    def test_sanitize_columns_reserved_stems_get_suffix(self):
        """Guard-rail: reserved names (_id, _row_hash, _created_at) must be
        remapped so they don't collide with the internal columns dynamic_loader
        adds to every table.
        """
        from api.services.csv_parse import sanitize_columns

        out = sanitize_columns(["_id", "_row_hash", "_created_at"])
        for name in out:
            self.assertNotIn(name, {"_id", "_row_hash", "_created_at"})


@pytest.mark.unit
class RequestValidation(unittest.TestCase):
    """Pydantic constraints and explicit guards — no database needed."""

    def test_preview_rejects_empty_filename(self):
        r = client.post("/api/csv/preview", json={"fileName": "", "content": SMALL_CSV})
        self.assertEqual(r.status_code, 422)

    def test_preview_rejects_empty_content(self):
        r = client.post("/api/csv/preview", json={"fileName": "a.csv", "content": ""})
        self.assertEqual(r.status_code, 422)

    def test_preview_rejects_overlong_filename(self):
        r = client.post("/api/csv/preview",
                        json={"fileName": "x" * 256, "content": SMALL_CSV})
        self.assertEqual(r.status_code, 422)

    def test_upload_rejects_unknown_mode(self):
        r = client.post("/api/csv/upload", json={
            "fileName": "a.csv", "content": SMALL_CSV, "mode": "sideways"})
        self.assertEqual(r.status_code, 422)

    def test_upload_te_mode_requires_target_table(self):
        r = client.post("/api/csv/upload", json={
            "fileName": "a.csv", "content": SMALL_CSV, "mode": "te"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("targetTable", r.text)

    def test_oversized_upload_is_rejected(self):
        from api.config import settings
        oversized = "x" * (settings.MAX_UPLOAD_BYTES + 1)
        r = client.post("/api/csv/preview",
                        json={"fileName": "big.csv", "content": oversized})
        self.assertEqual(r.status_code, 413)


@pytest.mark.unit
@pytest.mark.security
class TableNameGuards(unittest.TestCase):
    """The rows endpoint interpolates an identifier, so its guard matters."""

    def test_non_upload_tables_are_rejected(self):
        for name in ("organisations", "personnel", "pg_catalog", "users"):
            with self.subTest(table=name):
                r = client.get(f"/api/csv/tables/{name}/rows")
                self.assertEqual(r.status_code, 422,
                                 f"non-upload table accepted: {name}")

    def test_overlong_names_are_rejected(self):
        r = client.get(f"/api/csv/tables/csv_{'x' * 70}/rows")
        self.assertEqual(r.status_code, 422)

    # NOTE: names such as "csv_a'--" or "csv_a; DROP TABLE personnel" pass this
    # endpoint's prefix+length guard and reach the database layer. They are
    # still safe there — the csv_files lookup is parameterised, an unregistered
    # name returns 404, and psycopg2.sql.Identifier quotes the identifier — but
    # proving that needs a live database, so it is asserted in
    # CsvPipelineWithDatabase.test_injection_shaped_names_are_not_served.
    # A stricter guard (e.g. ^csv_[a-f0-9]{16}$) would reject them at the door.

    def test_identifiers_are_never_string_formatted(self):
        """Every SQL identifier must go through psycopg2.sql.Identifier.

        Parsed from the AST rather than grepped, so a comment cannot trip it
        and a real f-string cannot slip past.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "api"
        offenders = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                is_execute = isinstance(func, ast.Attribute) and func.attr == "execute"
                if is_execute and node.args and isinstance(node.args[0], ast.JoinedStr):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [],
                         f"execute() called with an f-string at {offenders}")
