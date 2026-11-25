"""Schema validator tests.

A small subset of these test pure functions on a fake `information_schema`
without needing a real database. The rest hit a live PostgreSQL.
"""
from __future__ import annotations

import pytest

from src.schema_validator import TYPE_FAMILY, validate_schema, ensure_staging_table


# ----------------------------- Unit tier -------------------------------------

@pytest.mark.unit
def test_type_family_covers_common_types():
    """TYPE_FAMILY must cover the types used in config.yaml; a missing entry causes silent schema mismatches."""
    expected = {"integer", "text", "varchar", "date", "numeric", "boolean"}
    assert expected.issubset(TYPE_FAMILY.keys())


@pytest.mark.unit
def test_text_family_accepts_varchar_and_text():
    """PostgreSQL reports text columns as 'text' or 'character varying'; both must map to the 'text' family."""
    assert "character varying" in TYPE_FAMILY["text"]
    assert "text" in TYPE_FAMILY["text"]


# ------------------------ Integration tier (DB) ------------------------------

@pytest.mark.integration
def test_validate_schema_passes_for_well_formed_table(
    pg_conn, users_job, fresh_target_table
):
    """Given fresh_target_table (drops + recreates from users.sql), validate_schema should pass all checks."""
    result = validate_schema(pg_conn, users_job)
    failed = [c for c in result.checks if not c.passed]
    assert result.passed, f"Unexpected failures: {failed}"


@pytest.mark.integration
def test_validate_schema_fails_when_table_missing(pg_conn, users_job):
    """Given the target table has been dropped, validate_schema should fail with a target_table_exists check failure."""
    with pg_conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{users_job.target_table}" CASCADE')
    pg_conn.commit()

    result = validate_schema(pg_conn, users_job)
    assert not result.passed
    assert any(
        c.name == "target_table_exists" and not c.passed for c in result.checks
    )


@pytest.mark.integration
def test_ensure_staging_table_creates_mirror(
    pg_conn, users_job, fresh_target_table
):
    """Given fresh_target_table, ensure_staging_table should create a staging table containing all db_column names from the job config."""
    ensure_staging_table(pg_conn, users_job)
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (users_job.staging_table,),
        )
        cols = [r[0] for r in cur.fetchall()]
    expected = [c.db_column for c in users_job.columns]
    assert set(expected).issubset(set(cols))
