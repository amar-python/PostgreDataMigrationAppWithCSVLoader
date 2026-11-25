"""#349 (CLI-03): the staging table must have the exact column types of the target table.

``ensure_staging_table`` built staging from ``information_schema`` ``data_type``, which has no precision, scale or length.
So ``NUMERIC(12,2)`` became plain ``numeric`` and ``CHAR(2)`` became ``character``, which is ``CHAR(1)``:

  * a CSV value ``1250.555`` was stored exactly in staging, so the staging-to-CSV comparison passed, then promotion
    saved ``1250.56`` in the real table and nothing checked it: the report said "success" with a changed value;
  * a ``CHAR(2)`` column could not load at all ("value too long for type character(1)").

The fix reads ``format_type(atttypid, atttypmod)``, which gives ``numeric(12,2)``, ``character(2)`` and
``character varying(20)``. These are database tests (marker ``integration``); they need PostgreSQL.

What must hold:
  * staging has the same ``format_type`` as the target for every column (varchar(n), numeric(p,s), character(n), text,
    integer, and plain numeric), without copying NOT NULL (staging accepts everything so it can be validated);
  * a CHAR(2) column loads;
  * a value the target's scale would change (1250.555 into NUMERIC(12,2)) blocks the job and leaves the target empty;
  * a value that fits (1250.55) loads and reads back unchanged.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.config import ColumnSpec, JobConfig, Thresholds, load_db_config
from src.migrator import run_job
from src.reporting import Reporter
from src.schema_validator import ensure_staging_table

pytestmark = pytest.mark.integration

TABLE = "cli03_types"

DDL = f"""
CREATE TABLE {TABLE} (
    id      INTEGER       PRIMARY KEY,
    price   NUMERIC(12,2) NOT NULL,
    code    CHAR(2)       NOT NULL,
    label   VARCHAR(20),
    note    TEXT,
    ratio   NUMERIC
)
"""


@pytest.fixture
def table(pg_conn):
    """The probe table, dropped before and after (and the staging table with it)."""
    def drop():
        pg_conn.rollback()
        with pg_conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{TABLE}_staging" CASCADE')
            cur.execute(f'DROP TABLE IF EXISTS "{TABLE}" CASCADE')
        pg_conn.commit()
    drop()
    with pg_conn.cursor() as cur:
        cur.execute(DDL)
    pg_conn.commit()
    yield TABLE
    drop()


def make_job(tmp_path: Path, rows: list[str]) -> JobConfig:
    csv = tmp_path / "types.csv"
    csv.write_text("id,price,code,label,note,ratio\n" + "\n".join(rows) + "\n", encoding="utf-8")
    schema = tmp_path / "types_schema.sql"
    schema.write_text(DDL, encoding="utf-8")
    return JobConfig(
        name="types", source_csv=csv, target_table=TABLE, schema_file=schema, delimiter=",", encoding="utf-8",
        has_header=True, null_values=["", "NULL"],
        columns=[ColumnSpec("id", "id", "integer", nullable=False),
                 ColumnSpec("price", "price", "numeric", nullable=False),
                 ColumnSpec("code", "code", "text", nullable=False, max_length=2),
                 ColumnSpec("label", "label", "text", nullable=True, max_length=20),
                 ColumnSpec("note", "note", "text", nullable=True),
                 ColumnSpec("ratio", "ratio", "numeric", nullable=True)],
        primary_key="id", thresholds=Thresholds(min_rows=1))


def column_types(pg_conn, table_name: str) -> dict[str, tuple[str, bool]]:
    """column -> (format_type, NOT NULL) straight from pg_attribute."""
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull FROM pg_attribute a "
            "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum", (table_name,))
        return {name: (typ, notnull) for name, typ, notnull in cur.fetchall()}


def test_the_target_really_has_the_exact_types_this_test_relies_on(pg_conn, table):
    types = {k: v[0] for k, v in column_types(pg_conn, table).items()}
    assert types == {"id": "integer", "price": "numeric(12,2)", "code": "character(2)",
                     "label": "character varying(20)", "note": "text", "ratio": "numeric"}


def test_staging_has_the_exact_types_of_the_target(pg_conn, table, tmp_path):
    job = make_job(tmp_path, ["1,10.00,AB,x,n,1.5"])
    ensure_staging_table(pg_conn, job)
    target, staging = column_types(pg_conn, table), column_types(pg_conn, f"{table}_staging")
    assert {k: v[0] for k, v in staging.items()} == {k: v[0] for k, v in target.items()}, (
        "staging lost precision, scale or length: it must be built from format_type, not information_schema.data_type")


def test_staging_does_not_copy_not_null(pg_conn, table, tmp_path):
    """Staging accepts everything so the validator can report it; that must survive the change."""
    ensure_staging_table(pg_conn, make_job(tmp_path, ["1,10.00,AB,x,n,1.5"]))
    staging = column_types(pg_conn, f"{table}_staging")
    assert target_has_not_null(pg_conn, table) and not any(notnull for _, notnull in staging.values())


def target_has_not_null(pg_conn, table_name: str) -> bool:
    return any(notnull for _, notnull in column_types(pg_conn, table_name).values())


def test_a_char_column_loads(pg_conn, table, tmp_path):
    """CHAR(2) used to become character (CHAR(1)) in staging and the load failed with 'value too long'."""
    job = make_job(tmp_path, ["1,10.00,AB,first,n,1.5", "2,20.50,CD,second,n,2"])
    reporter = Reporter()
    ok = run_job(job, load_db_config(), reporter)
    assert ok, reporter.job_reports[-1].error
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT id, code FROM "{TABLE}" ORDER BY id')
        assert cur.fetchall() == [(1, "AB"), (2, "CD")]


def test_a_value_the_target_scale_would_change_blocks_the_job_and_leaves_the_target_empty(pg_conn, table, tmp_path):
    """1250.555 into NUMERIC(12,2): staging used to hold it exactly, so the check passed and promotion rounded it."""
    job = make_job(tmp_path, ["1,1250.555,AB,x,n,1"])
    reporter = Reporter()
    ok = run_job(job, load_db_config(), reporter)
    report = reporter.job_reports[-1]
    assert not ok, "the job reported success while the value in the target would have been 1250.56, not 1250.555"
    assert report.error == "Integrity audit failed", report.error
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
        assert cur.fetchone()[0] == 0, "a blocked job must not promote anything"


def test_a_value_that_fits_loads_and_reads_back_unchanged(pg_conn, table, tmp_path):
    job = make_job(tmp_path, ["1,1250.55,AB,x,n,0.123456789"])
    reporter = Reporter()
    assert run_job(job, load_db_config(), reporter), reporter.job_reports[-1].error
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT price, ratio FROM "{TABLE}"')
        price, ratio = cur.fetchone()
    assert price == Decimal("1250.55") and ratio == Decimal("0.123456789"), "plain numeric keeps all its digits"
