"""#350 (CLI-04): a row with too few fields must be rejected, not loaded with NULLs.

The "row shape" check only caught rows that were too long (pandas raises on those). A row with a missing field passed:
with the header ``id,email,country`` the row ``2,b@x.com`` loaded with ``country`` as NULL, and only a column marked
required would notice. A truncated export therefore loaded with missing values and passed every check. The loader
(``csv.DictReader`` returns ``None`` for a missing field, which is not in the null set) did the same.

What must hold:
  * a row with too few fields is rejected, with its line number, whichever column is missing (required or not);
  * a row with too many fields is still rejected;
  * a genuinely empty value (``2,b@x.com,``) is still accepted: the check separates "missing field" from "empty field";
  * blank lines between rows are not short rows;
  * it holds with and without a header row;
  * the loader itself refuses a short row too (defence in depth, for a caller that skips the pre-import check).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ColumnSpec, JobConfig, Thresholds, load_db_config
from src.ingestion import load_csv_to_staging
from src.pre_import_validator import validate_csv
from src.schema_validator import ensure_staging_table

ROOT = Path(__file__).resolve().parents[1]
EDGE = ROOT / "input_data" / "edge_cases"
HEADER = "id,email,full_name,signup_date,country,lifetime_value"
GOOD = "1,a@example.com,A Example,2024-01-01,US,1.00"


def job_for(csv: Path, *, has_header: bool = True, delimiter: str = ",") -> JobConfig:
    return JobConfig(
        name="shape", source_csv=csv, target_table="users", schema_file=ROOT / "input_data" / "users_schema.sql",
        delimiter=delimiter, encoding="utf-8", has_header=has_header, null_values=["", "NULL", "N/A", "null"],
        columns=[ColumnSpec("id", "id", "integer", nullable=False),
                 ColumnSpec("email", "email", "text", nullable=False, max_length=255),
                 ColumnSpec("full_name", "full_name", "text", nullable=False, max_length=200),
                 ColumnSpec("signup_date", "signup_date", "date", nullable=False),
                 ColumnSpec("country", "country", "text", nullable=True, max_length=2),
                 ColumnSpec("lifetime_value", "lifetime_value", "numeric", nullable=True)],
        primary_key="id", thresholds=Thresholds(min_rows=1))


def shape_check(stage):
    return next(c for c in stage.checks if c.name == "row_shape_consistent")


def write(tmp_path: Path, *lines: str, name: str = "data.csv") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.unit
def test_the_shipped_short_row_fixture_is_rejected_with_its_line_number():
    stage, df = validate_csv(job_for(EDGE / "users_short.csv"))
    check = shape_check(stage)
    assert not check.passed and not stage.passed
    assert "line 3" in check.detail, check.detail
    assert df is None, "a rejected file must not be handed on"


@pytest.mark.unit
def test_a_row_missing_only_a_non_required_column_is_rejected(tmp_path):
    """lifetime_value is optional, so the old required-column check could never see this."""
    stage, df = validate_csv(job_for(write(tmp_path, HEADER, GOOD, "2,b@example.com,B,2024-01-02,GB")))
    assert not shape_check(stage).passed and df is None


@pytest.mark.unit
def test_a_row_missing_the_last_two_fields_is_rejected_and_the_detail_says_how_many(tmp_path):
    stage, _ = validate_csv(job_for(write(tmp_path, HEADER, GOOD, "2,b@example.com,B,2024-01-02")))
    check = shape_check(stage)
    assert not check.passed and "line 3" in check.detail and "4" in check.detail and "6" in check.detail, check.detail


@pytest.mark.unit
def test_a_row_with_too_many_fields_is_still_rejected():
    stage, df = validate_csv(job_for(EDGE / "users_ragged.csv"))
    assert not shape_check(stage).passed and df is None


@pytest.mark.unit
def test_an_empty_value_is_not_a_missing_field(tmp_path):
    """2,b@example.com,B,2024-01-02,, has all six fields, two of them empty: accepted."""
    stage, df = validate_csv(job_for(write(tmp_path, HEADER, GOOD, "2,b@example.com,B Example,2024-01-02,,")))
    assert shape_check(stage).passed, shape_check(stage).detail
    assert len(df) == 2


@pytest.mark.unit
def test_blank_lines_between_rows_are_not_short_rows(tmp_path):
    stage, df = validate_csv(job_for(write(tmp_path, HEADER, GOOD, "", "2,b@example.com,B Example,2024-01-02,GB,2.00", "")))
    assert shape_check(stage).passed, shape_check(stage).detail
    assert len(df) == 2


@pytest.mark.unit
def test_a_quoted_field_with_a_comma_or_a_newline_is_one_field(tmp_path):
    stage, df = validate_csv(job_for(write(
        tmp_path, HEADER, GOOD, '2,b@example.com,"B, Example",2024-01-02,GB,2.00',
        '3,c@example.com,"C\nExample",2024-01-03,AU,3.00')))
    assert shape_check(stage).passed, shape_check(stage).detail
    assert len(df) == 3


@pytest.mark.unit
def test_without_a_header_the_width_is_the_number_of_configured_columns(tmp_path):
    job = job_for(write(tmp_path, GOOD, "2,b@example.com,B,2024-01-02,GB"), has_header=False)
    stage, df = validate_csv(job)
    check = shape_check(stage)
    assert not check.passed and "line 2" in check.detail and df is None


@pytest.mark.unit
def test_a_tab_separated_short_row_is_rejected(tmp_path):
    rows = ["\t".join(HEADER.split(",")), "\t".join(GOOD.split(",")), "\t".join(["2", "b@example.com", "B"])]
    stage, df = validate_csv(job_for(write(tmp_path, *rows, name="data.tsv"), delimiter="\t"))
    assert not shape_check(stage).passed and df is None


@pytest.mark.integration
def test_the_loader_itself_refuses_a_short_row(pg_conn, fresh_target_table, users_job):
    """Defence in depth: a caller that goes straight to the loader must not get NULLs either."""
    from dataclasses import replace
    job = replace(users_job, source_csv=EDGE / "users_short.csv")
    ensure_staging_table(pg_conn, job)
    with pytest.raises(RuntimeError, match=r"line 3.*wrong number of fields"):
        load_csv_to_staging(pg_conn, job)
    pg_conn.rollback()
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{job.staging_table}"')
        assert cur.fetchone()[0] == 0, "nothing may be staged from a file with a short row"


@pytest.mark.integration
def test_the_loader_still_loads_a_file_with_empty_trailing_values(pg_conn, fresh_target_table, users_job, tmp_path):
    from dataclasses import replace
    path = write(tmp_path, HEADER, GOOD, "2,b@example.com,B Example,2024-01-02,,")
    job = replace(users_job, source_csv=path)
    ensure_staging_table(pg_conn, job)
    csv_rows, staged = load_csv_to_staging(pg_conn, job)
    assert (csv_rows, staged) == (2, 2)
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT country, lifetime_value FROM "{job.staging_table}" WHERE id = 2')
        assert cur.fetchone() == (None, None), "an empty value is NULL, as before"
