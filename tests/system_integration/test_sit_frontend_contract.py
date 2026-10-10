"""System integration tests — the seams between components.

* API ↔ frontend: every response the live API produces must satisfy the zod
  schemas the React app validates it with (csv-table-hub-main/src/lib/
  csv.functions.ts). The enums are read from the TypeScript source, so a
  change on either side that breaks the other fails here.
* API ↔ PostgreSQL: bootstrap is idempotent and the registry / T&E schema the
  API depends on are present with the expected columns.
* API ↔ deploy scripts: the T&E whitelist in api/config.py matches the tables
  that build/te_core_schema.sql creates.

Requires a provisioned dev database (PGDATABASE=te_mgmt_dev).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from api import db
from api.config import TE_TABLES, settings
from api.services.csv_parse import ALLOWED_TYPES

pytestmark = pytest.mark.sit

ROOT = Path(__file__).resolve().parents[2]
TS_CONTRACT = ROOT / "csv-table-hub-main" / "src" / "lib" / "csv.functions.ts"
TE_SCHEMA_SQL = ROOT / "build" / "te_core_schema.sql"


def _ts_enum(after: str) -> set[str]:
    """Values of the first z.enum([...]) that follows ``after`` in the TS file."""
    src = TS_CONTRACT.read_text(encoding="utf-8")
    start = src.index(after)
    m = re.search(r"z\.enum\(\[(.*?)\]\)", src[start:], re.S)
    assert m, f"no z.enum after {after!r} in {TS_CONTRACT}"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


@pytest.fixture(scope="module")
def contract():
    return {
        "column_types": _ts_enum("const columnTypeSchema"),
        "log_steps": _ts_enum("step: z.enum"),
        "log_levels": _ts_enum("level: z.enum"),
        "invalid_reasons": _ts_enum('status: z.literal("invalid_structure")'),
        "duplicate_reasons": _ts_enum('status: z.literal("duplicate_file")'),
    }


def _assert_logs(logs, contract):
    for entry in logs:
        assert isinstance(entry["ts"], int) and isinstance(entry["message"], str)
        assert entry["step"] in contract["log_steps"], f"step {entry['step']!r} unknown to the UI"
        assert entry["level"] in contract["log_levels"]
        if "count" in entry:
            assert isinstance(entry["count"], int)


def _assert_row_errors(errors):
    for e in errors:
        assert isinstance(e["rowNumber"], int) and isinstance(e["reason"], str)
        for optional in ("column", "value"):
            if optional in e:
                assert isinstance(e[optional], str)


def _upload(client, cleanup, name, content, **extra):
    cleanup.append(name)
    return client.post("/api/csv/upload", json={"fileName": name, "content": content, **extra}).json()


class TestStaticContract:
    def test_column_type_enum_matches_backend_whitelist(self, contract):
        """SIT-01 the UI's ColumnType enum equals the API's ALLOWED_TYPES."""
        assert contract["column_types"] == set(ALLOWED_TYPES)

    def test_te_whitelist_matches_schema_ddl(self):
        """SIT-02 every T&E table the API whitelists is created by te_core_schema.sql."""
        ddl = TE_SCHEMA_SQL.read_text(encoding="utf-8").lower()
        # Table names are psql variables: CREATE TABLE ... :"schema_name".:"tbl_<name>"
        created = set(re.findall(r'create table if not exists :"schema_name"\.:"tbl_([a-z_]+)"', ddl))
        assert set(TE_TABLES) <= created, set(TE_TABLES) - created

    def test_frontend_sends_api_key_header_the_api_reads(self):
        """SIT-03 the UI sends X-API-Key, which CORS allows and auth reads."""
        from api.main import app

        assert '"X-API-Key"' in TS_CONTRACT.read_text(encoding="utf-8")
        cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        assert "X-API-Key" in cors.kwargs["allow_headers"]


class TestLiveResponsesSatisfyUiSchemas:
    def test_ok_upload(self, live_api, registry_cleanup, unique_tag, contract):
        """SIT-04 status=ok upload response matches uploadResultSchema."""
        r = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv",
                    f"a,b\n1,{unique_tag}\nx,y\n", types=["int8", "text"])
        assert r["status"] == "ok"
        assert isinstance(r["fileId"], str) and isinstance(r["tableName"], str)
        for key in ("totalRows", "insertedRows", "duplicateRowsSkipped", "failedRows"):
            assert isinstance(r[key], int)
        assert set(r["types"]) <= contract["column_types"]
        assert r["replacedFileName"] is None or isinstance(r["replacedFileName"], str)
        _assert_row_errors(r["rowErrors"])
        _assert_logs(r["logs"], contract)

    def test_duplicate_upload(self, live_api, registry_cleanup, unique_tag, contract):
        """SIT-05 status=duplicate_file response matches the UI schema."""
        content = f"a\n{unique_tag}\n"
        _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", content)
        r = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", content)
        assert r["status"] == "duplicate_file"
        assert r["reason"] in contract["duplicate_reasons"]
        assert isinstance(r["existingFileName"], str) and isinstance(r["existingRowCount"], int)
        _assert_logs(r["logs"], contract)

    @pytest.mark.parametrize("content", ["\n", "a,b\n", ",\n1,2\n"])
    def test_invalid_structure_upload(self, live_api, registry_cleanup, unique_tag, contract,
                                      content):
        """SIT-06 status=invalid_structure reasons are ones the UI understands."""
        r = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", content)
        assert r["status"] == "invalid_structure"
        assert r["reason"] in contract["invalid_reasons"] and isinstance(r["message"], str)
        _assert_logs(r["logs"], contract)

    def test_error_upload(self, live_api, registry_cleanup, unique_tag, contract):
        """SIT-07 status=error response matches the UI schema."""
        r = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", f"a\n{unique_tag}\n",
                    types=["int8", "int8"])
        assert r["status"] == "error" and isinstance(r["message"], str)
        _assert_logs(r["logs"], contract)

    def test_te_upload(self, live_api, registry_cleanup, te_org_cleanup, unique_tag, contract):
        """SIT-08 a T&E-mode response (including DB-side row errors) matches the UI schema."""
        org = f"SIT_{unique_tag}"
        te_org_cleanup.append(org)
        r = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv",
                    f"name,org_type,country\n{org},prime,AU\n{org}_x,bogus,AU\n",
                    mode="te", targetTable="organisations")
        te_org_cleanup.append(f"{org}_x")
        assert r["status"] == "ok" and r["types"] == []
        _assert_row_errors(r["rowErrors"])
        _assert_logs(r["logs"], contract)

    def test_files_list(self, live_api, registry_cleanup, unique_tag):
        """SIT-09 /api/csv/files entries match csvFileSummarySchema."""
        _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", f"a\n{unique_tag}\n")
        files = live_api.get("/api/csv/files").json()
        assert files
        for f in files:
            assert isinstance(f["id"], str) and isinstance(f["file_name"], str)
            assert isinstance(f["table_name"], str) and isinstance(f["row_count"], int)
            assert all(isinstance(c, str) for c in f["column_names"])
            assert isinstance(f["created_at"], str)

    def test_preview_ok(self, live_api, contract):
        """SIT-10 /api/csv/preview ok response matches csvPreviewResultSchema."""
        r = live_api.post("/api/csv/preview", json={"fileName": "p.csv",
                                                    "content": "name,org_type,country\nA,prime,AU\n"}).json()
        assert r["status"] == "ok"
        assert set(r["inferredTypes"]) <= contract["column_types"]
        assert all(isinstance(c, str) for row in r["sampleRows"] for c in row)
        assert r["teTableMatch"] == "organisations"

    def test_table_rows_values_are_json_primitives(self, live_api, registry_cleanup, unique_tag):
        """SIT-11 row values are string/number/boolean/null as previewRowsSchema requires."""
        up = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv",
                     f"d,t,b\n2024-01-01,{unique_tag},true\n", types=["date", "text", "boolean"])
        rows = live_api.get(f"/api/csv/tables/{up['tableName']}/rows").json()["rows"]
        for row in rows:
            assert all(v is None or isinstance(v, (str, int, float, bool)) for v in row.values())

    def test_te_tables(self, live_api):
        """SIT-12 /api/te/tables entries match teTableInfoSchema."""
        for t in live_api.get("/api/te/tables").json():
            assert isinstance(t["table"], str) and isinstance(t["exists"], bool)
            assert isinstance(t["rowCount"], int) and t["rowCount"] >= 0


class TestApiDatabaseIntegration:
    def test_bootstrap_is_idempotent(self, live_api):
        """SIT-13 running bootstrap again on a live schema is a harmless no-op."""
        before = live_api.get("/api/csv/files").json()
        db.bootstrap()
        assert live_api.get("/api/csv/files").json() == before

    def test_registry_tables_have_expected_columns(self, live_api):
        """SIT-14 csv_files and audit_log carry every column the API reads/writes."""
        with db.Conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s", (settings.UPLOADS_SCHEMA,))
            cols: dict[str, set] = {}
            for table, col in cur.fetchall():
                cols.setdefault(table, set()).add(col)
        assert {"id", "file_name", "file_hash", "table_name", "mode", "row_count",
                "column_names", "created_at"} <= cols["csv_files"]
        assert {"id", "action", "file_id", "file_name", "table_name", "mode",
                "performed_at"} <= cols["audit_log"]

    def test_dynamic_tables_live_only_in_uploads_schema(self, live_api, registry_cleanup,
                                                        unique_tag):
        """SIT-15 a dynamic upload creates its table in the uploads schema, nowhere else."""
        up = _upload(live_api, registry_cleanup, f"sit_{unique_tag}.csv", f"a\n{unique_tag}\n")
        with db.Conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
                        (up["tableName"],))
            assert [r[0] for r in cur.fetchall()] == [settings.UPLOADS_SCHEMA]

    def test_te_row_counts_track_postgres_statistics(self, live_api):
        """SIT-16 /api/te/tables row counts agree with COUNT(*) once statistics are fresh."""
        with db.Conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'ANALYZE "{settings.TE_SCHEMA}".organisations')  # nosec B608 — fixed identifier
                cur.execute(f'SELECT COUNT(*) FROM "{settings.TE_SCHEMA}".organisations')  # nosec B608
                actual = cur.fetchone()[0]
            conn.autocommit = False
        reported = next(t for t in live_api.get("/api/te/tables").json() if t["table"] == "organisations")
        assert reported["rowCount"] == actual
