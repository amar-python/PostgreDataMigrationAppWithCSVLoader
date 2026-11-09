"""Dynamic mode: column types are confirmed before a table exists (#195).

Product-owner decision (4 Nov 2026): require type confirmation before a
dynamic-mode table is created, and record a provenance flag. Dynamic tables stay
out of the T&E import path. This does not reopen BR-22 or the multi-engine work.

The contract under test:

    POST /api/csv/upload  (dynamic mode)
      typesConfirmed absent/false -> nothing created or registered; the response
                                     carries the inferred types to show
      typesConfirmed true + types -> table created with those types; provenance
                                     user_confirmed, in the response and the registry
"""

from __future__ import annotations

import hashlib

import pytest
from psycopg2 import sql

from api.config import TE_TABLES
from api.db import Conn
from api.tenancy import uploads_schema

pytestmark = pytest.mark.integration

# `clearance` and the date are the mis-typing examples from the review feedback.
CONTENT = "id,clearance,start\n1,TS,2026-01-01\n2,S,2026-02-02\n"
INFERRED = ["int8", "text", "date"]


def _table(content: str) -> str:
    return "csv_" + hashlib.sha256(content.encode()).hexdigest()[:16]


def _table_exists(name: str) -> bool:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                    (uploads_schema(), name))
        return cur.fetchone() is not None


def _registry(file_name: str) -> list[tuple]:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT table_name, types_provenance FROM {}.csv_files WHERE file_name = %s")
                    .format(sql.Identifier(uploads_schema())), (file_name,))
        return cur.fetchall()


def _column_types(table: str) -> dict[str, str]:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s", (uploads_schema(), table))
        return dict(cur.fetchall())


def _upload(client, name, content, **extra):
    return client.post("/api/csv/upload", json={"fileName": name, "content": content, **extra}).json()


def test_no_table_exists_before_confirmation(live_api, registry_cleanup, unique_tag):
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"3,C,2026-03-03\n4,{unique_tag},2026-04-04\n"
    registry_cleanup.append(name)

    res = _upload(live_api, name, content)          # no typesConfirmed

    assert res["status"] == "types_unconfirmed", res
    assert res["inferredTypes"] == INFERRED, "the inferred types are returned so they can be shown"
    assert res["columns"] == ["id", "clearance", "start"]
    assert not _table_exists(_table(content)), "a table was created before anyone confirmed its types"
    assert _registry(name) == [], "an unconfirmed upload must not be registered"
    # Still attributable: the attempt is on the audit trail as a rejection, with its original.
    detail = live_api.get(f"/api/csv/uploads/{res['uploadId']}").json()
    assert detail["status"] == "rejected"


def test_explicit_false_is_the_same_as_absent(live_api, registry_cleanup, unique_tag):
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"5,{unique_tag},2026-05-05\n"
    registry_cleanup.append(name)
    assert _upload(live_api, name, content, typesConfirmed=False)["status"] == "types_unconfirmed"
    assert not _table_exists(_table(content))


def test_confirming_creates_the_table_with_the_confirmed_types(live_api, registry_cleanup, unique_tag):
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"6,{unique_tag},2026-06-06\n"
    registry_cleanup.append(name)
    # The user accepts clearance and the date, but changes id from the inferred int8 to text.
    confirmed = ["text", "text", "date"]

    res = _upload(live_api, name, content, typesConfirmed=True, types=confirmed)

    assert res["status"] == "ok", res
    assert res["types"] == confirmed
    types = _column_types(res["tableName"])
    assert (types["id"], types["clearance"], types["start"]) == ("text", "text", "date"), \
        "the table was created with the inferred types, not the confirmed ones"
    assert res["insertedRows"] == 3


def test_provenance_is_stored_and_returned(live_api, registry_cleanup, unique_tag):
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"7,{unique_tag},2026-07-07\n"
    registry_cleanup.append(name)

    res = _upload(live_api, name, content, typesConfirmed=True, types=INFERRED)

    assert res["status"] == "ok", res
    assert res["typesProvenance"] == "user_confirmed"                       # in the upload response
    assert _registry(name) == [(res["tableName"], "user_confirmed")]        # stored
    listed = [f for f in live_api.get("/api/csv/files").json() if f["file_name"] == name]
    assert [f["types_provenance"] for f in listed] == ["user_confirmed"]    # in the files list the UI reads


def test_confirmation_of_a_duplicate_still_reports_the_duplicate(live_api, registry_cleanup, unique_tag):
    """Confirmation gates table creation; it must not change duplicate handling."""
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"8,{unique_tag},2026-08-08\n"
    registry_cleanup.append(name)
    assert _upload(live_api, name, content, typesConfirmed=True, types=INFERRED)["status"] == "ok"
    assert _upload(live_api, name, content, typesConfirmed=True, types=INFERRED)["status"] == "duplicate_file"


def test_te_mode_ignores_typesConfirmed(live_api, te_org_cleanup, registry_cleanup, unique_tag):
    """T&E types come from the T&E schema, so confirmation is neither needed nor recorded."""
    name = f"tc_{unique_tag}.csv"
    org = f"TC_{unique_tag}"
    registry_cleanup.append(name)
    te_org_cleanup.append(org)

    res = _upload(live_api, name, f"name,org_type,country\n{org},government,AU\n",
                  mode="te", targetTable="organisations")

    assert res["status"] == "ok", res
    assert "typesProvenance" not in res
    assert [r[1] for r in _registry(name)] == [None]


# ── dynamic tables stay out of the T&E import path ───────────────────────────
def test_te_import_rejects_a_dynamic_mode_table_as_its_target(live_api, registry_cleanup, unique_tag):
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"9,{unique_tag},2026-09-09\n"
    registry_cleanup.append(name)
    dyn = _upload(live_api, name, content, typesConfirmed=True, types=INFERRED)
    assert dyn["status"] == "ok", dyn
    table = dyn["tableName"]
    before = live_api.get(f"/api/csv/tables/{table}/rows").json()["rows"]
    assert table not in TE_TABLES

    other = f"tc_te_{unique_tag}.csv"
    registry_cleanup.append(other)
    for target in (table, f"{uploads_schema()}.{table}"):
        res = _upload(live_api, other, "id,clearance,start\n99,X,2026-12-12\n",
                      mode="te", targetTable=target)
        assert res["status"] == "error", (target, res)
        assert "not a T&E table" in res["message"], (target, res)

    assert live_api.get(f"/api/csv/tables/{table}/rows").json()["rows"] == before, \
        "a T&E import wrote into a dynamic-mode table"
    assert _registry(other) == [], "the rejected T&E import was registered"


def test_a_dynamic_table_is_never_suggested_as_a_te_match(live_api, registry_cleanup, unique_tag):
    """The preview's teTableMatch only ever names a table from TE_TABLES."""
    name = f"tc_{unique_tag}.csv"
    content = CONTENT + f"10,{unique_tag},2026-10-10\n"
    registry_cleanup.append(name)
    dyn = _upload(live_api, name, content, typesConfirmed=True, types=INFERRED)
    preview = live_api.post("/api/csv/preview", json={"fileName": name, "content": content}).json()
    assert preview["teTableMatch"] in (None, *TE_TABLES)
    assert preview["teTableMatch"] != dyn["tableName"]
