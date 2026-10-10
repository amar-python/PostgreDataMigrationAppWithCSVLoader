"""User acceptance tests — each test is one acceptance criterion of a user story,
written Given / When / Then from the point of view of the data migrator who
uses the CSV Migrator UI. They drive the same HTTP calls the UI makes, using
the sample files shipped in build/csv/samples/.

Persona: "Migrator" — moves spreadsheet data into PostgreSQL without SQL.

Requires a provisioned dev database (PGDATABASE=te_mgmt_dev).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from api.config import settings

pytestmark = pytest.mark.uat

SAMPLES = Path(__file__).resolve().parents[2] / "build" / "csv" / "samples"


def _sample(name: str, tag: str) -> str:
    """Sample file content with a unique trailing row so each run hashes uniquely."""
    text = (SAMPLES / name).read_text(encoding="utf-8")
    header = next(csv.reader(io.StringIO(text)))
    return text.rstrip("\n") + "\n" + ",".join(["9999"] + [tag] * (len(header) - 1)) + "\n"


def _upload(client, cleanup, name, content, **extra):
    cleanup.append(name)
    return client.post("/api/csv/upload", json={"fileName": name, "content": content, **extra}).json()


class TestUS01ImportAnyCsv:
    """US-01 As a Migrator I want to upload a CSV and have a table created for it,
    so that I can migrate data without writing DDL."""

    @pytest.mark.parametrize("sample", ["customers.csv", "orders.csv", "inventory.csv"])
    def test_sample_file_becomes_a_table_with_every_row(self, live_api, registry_cleanup,
                                                        unique_tag, sample):
        """UAT-01 Given a sample CSV, when I import it, then every data row is stored."""
        content = _sample(sample, unique_tag)
        data_rows = len(list(csv.reader(io.StringIO(content)))) - 1
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}_{sample}", content)
        assert result["status"] == "ok"
        assert result["totalRows"] == result["insertedRows"] == data_rows
        assert result["failedRows"] == 0

    def test_quoted_commas_are_preserved(self, live_api, registry_cleanup, unique_tag):
        """UAT-02 Given a product name containing a comma, when imported, then it is
        stored as one value, not split across columns."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         _sample("orders.csv", unique_tag))
        rows = live_api.get(f"/api/csv/tables/{result['tableName']}/rows").json()["rows"]
        assert "Wireless headphones, black" in [r["product"] for r in rows]


class TestUS02PreviewBeforeImport:
    """US-02 As a Migrator I want to preview a file before importing it, so that I
    can confirm the columns and types are right."""

    def test_preview_shows_headers_types_and_sample(self, live_api, unique_tag):
        """UAT-03 Given customers.csv, when I preview it, then I see its headers,
        sensible inferred types and the first rows, and nothing is stored."""
        before = len(live_api.get("/api/csv/files").json())
        p = live_api.post("/api/csv/preview", json={
            "fileName": "customers.csv", "content": _sample("customers.csv", unique_tag)}).json()
        assert p["headers"] == ["id", "name", "email", "signup_date"]
        assert p["inferredTypes"][0] == "int8"
        assert p["sampleRows"][0][1] == "Alice Nguyen"
        assert len(live_api.get("/api/csv/files").json()) == before

    def test_preview_suggests_matching_te_table(self, live_api):
        """UAT-04 Given a file whose columns fit a T&E table, when I preview it,
        then that table is suggested."""
        p = live_api.post("/api/csv/preview", json={
            "fileName": "orgs.csv", "content": "name,org_type,country\nACME,prime,AU\n"}).json()
        assert p["teTableMatch"] == "organisations"

    def test_preview_explains_an_unusable_file(self, live_api):
        """UAT-05 Given a header-only file, when I preview it, then I am told why it
        cannot be imported."""
        p = live_api.post("/api/csv/preview", json={"fileName": "h.csv", "content": "a,b\n"}).json()
        assert p == {"status": "invalid_structure", "reason": "header_only"}


class TestUS03DuplicateProtection:
    """US-03 As a Migrator I want accidental re-uploads to be caught, so that I do
    not load the same data twice."""

    def test_reupload_is_flagged_with_the_original_file(self, live_api, registry_cleanup,
                                                        unique_tag):
        """UAT-06 Given I imported a file, when I upload the same content again,
        then I am told it duplicates the original and how many rows it holds."""
        content = _sample("customers.csv", unique_tag)
        first = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv", content)
        again = _upload(live_api, registry_cleanup, f"uat_{unique_tag}_copy.csv", content)
        assert again["status"] == "duplicate_file"
        assert again["existingFileName"] == f"uat_{unique_tag}.csv"
        assert again["existingRowCount"] == first["insertedRows"]

    def test_overwrite_replaces_the_data(self, live_api, registry_cleanup, unique_tag):
        """UAT-07 Given a duplicate warning, when I choose Overwrite, then the new
        data replaces the old and the file appears once in the list."""
        name = f"uat_{unique_tag}.csv"
        _upload(live_api, registry_cleanup, name, _sample("customers.csv", unique_tag))
        result = _upload(live_api, registry_cleanup, name,
                         _sample("customers.csv", unique_tag + "_v2"), overwrite=True)
        assert result["status"] == "ok" and result["overwritten"] is True
        names = [f["file_name"] for f in live_api.get("/api/csv/files").json()]
        assert names.count(name) == 1

    def test_repeated_rows_inside_a_file_load_once(self, live_api, registry_cleanup, unique_tag):
        """UAT-08 Given a file with the same row twice, when imported, then it is
        stored once and the summary says one duplicate was skipped."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         f"a,b\n{unique_tag},1\n{unique_tag},1\nz,2\n")
        assert result["insertedRows"] == 2 and result["duplicateRowsSkipped"] == 1


class TestUS04BadDataIsExplained:
    """US-04 As a Migrator I want each rejected row explained, so that I can fix
    the source file and re-import."""

    def test_each_bad_row_has_row_column_value_and_reason(self, live_api, registry_cleanup,
                                                          unique_tag):
        """UAT-09 Given a file with a bad date on row 2, when imported with a date
        column, then the error names row 2, the column, the value and why, and
        the good rows are still stored."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         f"who,joined\n{unique_tag},2024-01-01\nbob,31/12/2024\ncat,2024-02-02\n",
                         types=["text", "date"])
        assert result["insertedRows"] == 2 and result["failedRows"] == 1
        assert result["rowErrors"] == [{"rowNumber": 2, "column": "joined", "value": "31/12/2024",
                                        "reason": '"31/12/2024" is not a YYYY-MM-DD date'}]

    def test_summary_counts_reconcile(self, live_api, registry_cleanup, unique_tag):
        """UAT-10 Given a mixed file, when imported, then inserted + failed +
        duplicates equals the total rows processed."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         f"n,t\n1,{unique_tag}\n1,{unique_tag}\nx,y\n4,z\n", types=["int8", "text"])
        assert result["totalRows"] == (result["insertedRows"] + result["failedRows"]
                                       + result["duplicateRowsSkipped"]) == 4


class TestUS05LoadIntoTeTables:
    """US-05 As a T&E data owner I want to load a CSV into an existing T&E table,
    so that programme data lands in the governed schema."""

    def test_load_organisations(self, live_api, registry_cleanup, te_org_cleanup, unique_tag):
        """UAT-11 Given an organisations CSV, when I load it in T&E mode, then the
        rows are in te_dev.organisations and the load is listed."""
        orgs = [f"UAT_{unique_tag}_{i}" for i in range(3)]
        te_org_cleanup.extend(orgs)
        name = f"uat_{unique_tag}.csv"
        result = _upload(live_api, registry_cleanup, name,
                         "name,org_type,country\n" + "\n".join(f"{o},test_unit,AU" for o in orgs) + "\n",
                         mode="te", targetTable="organisations")
        assert result["status"] == "ok" and result["insertedRows"] == 3
        listed = next(f for f in live_api.get("/api/csv/files").json() if f["file_name"] == name)
        assert listed["table_name"] == f"{settings.TE_SCHEMA}.organisations"

    def test_wrong_columns_are_rejected_with_their_names(self, live_api, registry_cleanup,
                                                         unique_tag):
        """UAT-12 Given a CSV with columns the T&E table lacks, when I load it,
        then nothing is inserted and the unknown columns are named."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         f"name,favourite_colour\n{unique_tag},blue\n",
                         mode="te", targetTable="organisations")
        assert result["status"] == "error" and "favourite_colour" in result["message"]


class TestUS06ReviewMigratedData:
    """US-06 As a Migrator I want to see what has been migrated, so that I can
    verify and report on the migration."""

    def test_migrated_files_list_shows_counts_and_columns(self, live_api, registry_cleanup,
                                                          unique_tag):
        """UAT-13 Given I imported a file, when I open Migrated files, then it is
        listed first with its table, column names and row count."""
        name = f"uat_{unique_tag}.csv"
        result = _upload(live_api, registry_cleanup, name, _sample("inventory.csv", unique_tag))
        newest = live_api.get("/api/csv/files").json()[0]
        assert newest["file_name"] == name
        assert newest["column_names"] == ["sku", "description", "stock", "location"]
        assert newest["row_count"] == result["insertedRows"]

    def test_first_rows_can_be_previewed(self, live_api, registry_cleanup, unique_tag):
        """UAT-14 Given an imported file, when I click Preview, then I see its first
        rows in file order."""
        result = _upload(live_api, registry_cleanup, f"uat_{unique_tag}.csv",
                         _sample("customers.csv", unique_tag))
        rows = live_api.get(f"/api/csv/tables/{result['tableName']}/rows?limit=2").json()["rows"]
        assert [r["name"] for r in rows] == ["Alice Nguyen", "Brian O'Connor"]


class TestUS07AuditTrail:
    """US-07 As an administrator I want deletions recorded, so that removed data
    is traceable."""

    def test_deleting_a_file_is_audited(self, live_api, registry_cleanup, unique_tag,
                                        destructive_enabled):
        """UAT-15 Given deletion is enabled, when I delete an imported file, then it
        disappears from the list and the audit log records who/what/when."""
        name = f"uat_{unique_tag}.csv"
        result = _upload(live_api, registry_cleanup, name, _sample("customers.csv", unique_tag))
        assert live_api.delete(f"/api/csv/files/{result['fileId']}").status_code == 200
        assert name not in [f["file_name"] for f in live_api.get("/api/csv/files").json()]
        latest = live_api.get("/api/audit/log?limit=1").json()["entries"][0]
        assert (latest["action"], latest["fileName"], latest["tableName"]) == (
            "delete", name, result["tableName"])

    def test_deletion_is_blocked_unless_enabled(self, live_api, registry_cleanup, unique_tag,
                                                monkeypatch):
        """UAT-16 Given a default (safe) deployment, when someone tries to delete a
        file, then it is refused and the data stays."""
        monkeypatch.setattr(settings, "allow_destructive", False)
        name = f"uat_{unique_tag}.csv"
        result = _upload(live_api, registry_cleanup, name, _sample("customers.csv", unique_tag))
        assert live_api.delete(f"/api/csv/files/{result['fileId']}").status_code == 403
        assert name in [f["file_name"] for f in live_api.get("/api/csv/files").json()]
