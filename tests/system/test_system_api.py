"""System tests — the whole backend (FastAPI + services + PostgreSQL) exercised
through its public HTTP API only, the way the frontend uses it.

Requires a provisioned dev database (PGDATABASE=te_mgmt_dev). Fails, never
skips, when PostgreSQL is unreachable.
"""
from __future__ import annotations

import pytest

from api.config import settings

pytestmark = pytest.mark.system


def _upload(client, cleanup, name, content, **extra):
    cleanup.append(name)
    r = client.post("/api/csv/upload", json={"fileName": name, "content": content, **extra})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _file_by_name(client, name):
    return next((f for f in client.get("/api/csv/files").json() if f["file_name"] == name), None)


class TestHealth:
    def test_health_ok_with_bootstrapped_schema(self, live_api):
        """SYS-01 /api/health reports ok and the uploads schema once bootstrapped."""
        body = live_api.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["uploads_schema"] == settings.UPLOADS_SCHEMA
        assert body["postgres"].startswith("PostgreSQL")

    def test_openapi_lists_every_endpoint(self, live_api):
        """SYS-02 the OpenAPI document exposes every public route."""
        paths = set(live_api.get("/openapi.json").json()["paths"])
        assert {
            "/api/health", "/api/csv/preview", "/api/csv/upload", "/api/csv/files",
            "/api/csv/tables/{table_name}/rows", "/api/csv/files/{file_id}",
            "/api/te/tables", "/api/audit/log",
        } <= paths


class TestDynamicLifecycle:
    def test_upload_list_read_delete_audit(self, live_api, registry_cleanup, unique_tag,
                                           destructive_enabled):
        """SYS-03 full lifecycle: upload → listed → rows readable → delete →
        gone from list, rows 404, audit entry recorded."""
        name = f"sys_{unique_tag}.csv"
        up = _upload(live_api, registry_cleanup, name, f"k,v\n1,{unique_tag}\n2,b\n")
        assert up["status"] == "ok" and up["insertedRows"] == 2

        listed = _file_by_name(live_api, name)
        assert listed and listed["table_name"] == up["tableName"] and listed["row_count"] == 2

        rows = live_api.get(f"/api/csv/tables/{up['tableName']}/rows").json()["rows"]
        assert [r["v"] for r in rows] == [unique_tag, "b"]

        d = live_api.delete(f"/api/csv/files/{up['fileId']}")
        assert d.status_code == 200 and d.json() == {"status": "ok", "deleted": int(up["fileId"])}
        assert _file_by_name(live_api, name) is None
        assert live_api.get(f"/api/csv/tables/{up['tableName']}/rows").status_code == 404

        audit = live_api.get("/api/audit/log?limit=200").json()["entries"]
        entry = next(e for e in audit if e["fileId"] == int(up["fileId"]))
        assert entry["action"] == "delete" and entry["fileName"] == name

    def test_typed_columns_are_stored_typed(self, live_api, registry_cleanup, unique_tag):
        """SYS-04 caller-supplied types create typed columns; values come back typed."""
        name = f"sys_{unique_tag}.csv"
        up = _upload(live_api, registry_cleanup, name,
                     f"n,amount,day,flag,label\n7,1.50,2024-03-01,yes,{unique_tag}\n",
                     types=["int8", "numeric", "date", "boolean", "text"])
        assert up["status"] == "ok" and up["types"] == ["int8", "numeric", "date", "boolean", "text"]
        row = live_api.get(f"/api/csv/tables/{up['tableName']}/rows").json()["rows"][0]
        assert row["n"] == 7 and row["flag"] is True
        assert row["amount"] == "1.50" and row["day"] == "2024-03-01"

    def test_cast_failures_are_reported_and_good_rows_load(self, live_api, registry_cleanup,
                                                           unique_tag):
        """SYS-05 rows that fail type casting are reported; valid rows still load."""
        name = f"sys_{unique_tag}.csv"
        up = _upload(live_api, registry_cleanup, name,
                     f"n,label\n1,{unique_tag}\nabc,x\n3,y\n", types=["int8", "text"])
        assert up["insertedRows"] == 2 and up["failedRows"] == 1
        err = up["rowErrors"][0]
        assert err == {"rowNumber": 2, "column": "n", "value": "abc",
                       "reason": '"abc" is not a whole number'}

    def test_type_count_mismatch_is_rejected(self, live_api, registry_cleanup, unique_tag):
        """SYS-06 supplying the wrong number of types is a clear error, no table."""
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv",
                     f"a,b\n1,{unique_tag}\n", types=["int8"])
        assert up["status"] == "error" and "1 column types" in up["message"]

    def test_unsupported_type_is_rejected(self, live_api, registry_cleanup, unique_tag):
        """SYS-07 types outside the whitelist cannot reach CREATE TABLE."""
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv",
                     f"a\n{unique_tag}\n", types=["text; DROP TABLE x"])
        assert up["status"] == "error" and "Unsupported" in up["message"]

    def test_headers_are_sanitised_in_created_table(self, live_api, registry_cleanup, unique_tag):
        """SYS-08 messy headers become safe snake_case column names."""
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv",
                     f"First Name,E-Mail,2024 Total\n{unique_tag},a@b.c,9\n")
        assert up["columns"] == ["first_name", "e_mail", "col_2024_total"]
        row = live_api.get(f"/api/csv/tables/{up['tableName']}/rows").json()["rows"][0]
        assert {"first_name", "e_mail", "col_2024_total", "_id", "_row_hash"} <= set(row)


class TestDuplicatesAndOverwrite:
    def test_same_name_different_content_is_name_duplicate(self, live_api, registry_cleanup,
                                                           unique_tag):
        """SYS-09 a new file reusing an existing file name is flagged reason=name."""
        name = f"sys_{unique_tag}.csv"
        _upload(live_api, registry_cleanup, name, f"a\n{unique_tag}\n")
        dup = _upload(live_api, registry_cleanup, name, f"a\n{unique_tag}_v2\n")
        assert dup["status"] == "duplicate_file" and dup["reason"] == "name"
        assert dup["existingRowCount"] == 1

    def test_same_content_different_name_is_content_duplicate(self, live_api, registry_cleanup,
                                                              unique_tag):
        """SYS-10 identical content under another name is flagged reason=content."""
        content = f"a\n{unique_tag}\n"
        _upload(live_api, registry_cleanup, f"sys_{unique_tag}_1.csv", content)
        dup = _upload(live_api, registry_cleanup, f"sys_{unique_tag}_2.csv", content)
        assert dup["status"] == "duplicate_file" and dup["reason"] == "content"
        assert dup["existingFileName"] == f"sys_{unique_tag}_1.csv"

    def test_overwrite_replaces_previous_upload(self, live_api, registry_cleanup, unique_tag):
        """SYS-11 overwrite=true drops the old table and registers the new file once."""
        name = f"sys_{unique_tag}.csv"
        first = _upload(live_api, registry_cleanup, name, f"a\n{unique_tag}\n")
        second = _upload(live_api, registry_cleanup, name, f"a\n{unique_tag}\nz\n", overwrite=True)
        assert second["status"] == "ok" and second["overwritten"] is True
        assert second["replacedFileName"] == name
        assert [f["file_name"] for f in live_api.get("/api/csv/files").json()].count(name) == 1
        assert live_api.get(f"/api/csv/tables/{first['tableName']}/rows").status_code == 404


class TestLimitsAndGuards:
    def test_row_cap_rejects_oversized_file(self, live_api, registry_cleanup, unique_tag,
                                            monkeypatch):
        """SYS-12 API_MAX_ROWS rejects a file before any table is created."""
        monkeypatch.setattr(settings, "MAX_ROWS", 2)
        name = f"sys_{unique_tag}.csv"
        up = _upload(live_api, registry_cleanup, name, f"a\n{unique_tag}\n2\n3\n")
        assert up["status"] == "error" and "at most 2" in up["message"]
        assert _file_by_name(live_api, name) is None

    def test_row_error_list_is_capped(self, live_api, registry_cleanup, unique_tag, monkeypatch):
        """SYS-13 rowErrors is capped but failedRows reports the true count."""
        monkeypatch.setattr(settings, "MAX_ROW_ERRORS_REPORTED", 5)
        body = "n\n" + "\n".join(f"bad{i}_{unique_tag}" for i in range(20)) + "\n"
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv", body, types=["int8"])
        assert up["failedRows"] == 20 and len(up["rowErrors"]) == 5

    def test_upload_size_limit_returns_413(self, live_api, monkeypatch):
        """SYS-14 bodies above MAX_UPLOAD_BYTES are refused with 413."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
        r = live_api.post("/api/csv/upload", json={"fileName": "big.csv", "content": "a\n" + "x" * 20})
        assert r.status_code == 413

    def test_delete_disabled_by_default(self, live_api, monkeypatch):
        """SYS-15 DELETE is 403 unless API_ALLOW_DESTRUCTIVE is on."""
        monkeypatch.setattr(settings, "allow_destructive", False)
        assert live_api.delete("/api/csv/files/1").status_code == 403

    def test_rows_limit_is_clamped(self, live_api, registry_cleanup, unique_tag):
        """SYS-16 the rows endpoint clamps limit into 1..200."""
        body = "n\n" + "\n".join(f"{i}_{unique_tag}" for i in range(5)) + "\n"
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv", body)
        url = f"/api/csv/tables/{up['tableName']}/rows"
        assert len(live_api.get(url + "?limit=0").json()["rows"]) == 1
        assert len(live_api.get(url + "?limit=999").json()["rows"]) == 5

    @pytest.mark.parametrize("name", ["organisations", "pg_class", "csv_" + "x" * 70])
    def test_rows_endpoint_refuses_non_upload_tables(self, live_api, name):
        """SYS-17 only registered csv_* tables are readable through the API."""
        assert live_api.get(f"/api/csv/tables/{name}/rows").status_code in (404, 422)


class TestAuditLogEndpoint:
    def test_pagination_parameters_are_clamped(self, live_api):
        """SYS-18 limit is clamped into 1..200 and offset to >= 0."""
        assert live_api.get("/api/audit/log?limit=0").json()["limit"] == 1
        assert live_api.get("/api/audit/log?limit=5000").json()["limit"] == 200
        assert live_api.get("/api/audit/log?offset=-5").json()["offset"] == 0

    def test_entries_are_newest_first(self, live_api):
        """SYS-19 audit entries are ordered by performedAt descending."""
        entries = live_api.get("/api/audit/log?limit=50").json()["entries"]
        stamps = [e["performedAt"] for e in entries]
        assert stamps == sorted(stamps, reverse=True)


class TestTeMode:
    def test_te_tables_endpoint_lists_all_twelve(self, live_api):
        """SYS-20 /api/te/tables reports all 12 T&E tables as existing."""
        tables = live_api.get("/api/te/tables").json()
        assert len(tables) == 12 and all(t["exists"] for t in tables)

    def test_te_upload_and_registry(self, live_api, registry_cleanup, te_org_cleanup, unique_tag):
        """SYS-21 a T&E upload inserts rows and registers a schema-qualified table."""
        org = f"SYS_{unique_tag}"
        te_org_cleanup.append(org)
        name = f"sys_{unique_tag}.csv"
        up = _upload(live_api, registry_cleanup, name, f"name,org_type,country\n{org},academic,AU\n",
                     mode="te", targetTable="organisations")
        assert up["status"] == "ok" and up["insertedRows"] == 1
        assert up["tableName"] == f"{settings.TE_SCHEMA}.organisations"
        listed = _file_by_name(live_api, name)
        assert listed["mode"] == "te" and listed["row_count"] == 1

    def test_te_constraint_violation_is_per_row(self, live_api, registry_cleanup, te_org_cleanup,
                                                unique_tag):
        """SYS-22 a CHECK-constraint failure is reported per row; others insert."""
        good, bad = f"SYS_{unique_tag}_ok", f"SYS_{unique_tag}_bad"
        te_org_cleanup.extend([good, bad])
        up = _upload(live_api, registry_cleanup, f"sys_{unique_tag}.csv",
                     f"name,org_type,country\n{good},prime,AU\n{bad},not_a_type,AU\n",
                     mode="te", targetTable="organisations")
        assert up["insertedRows"] == 1 and up["failedRows"] == 1
        assert "check" in up["rowErrors"][0]["reason"].lower()
