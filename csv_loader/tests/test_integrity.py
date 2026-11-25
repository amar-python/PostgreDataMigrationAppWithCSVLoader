"""Integrity-check tests.

`_normalize` is a pure function so it gets a unit test here. The remaining
checks need a real database and are marked `integration`.
"""
from __future__ import annotations

import pytest

from src.integrity_checks import _normalize, run_integrity_checks
from src.ingestion import load_csv_to_staging
from src.pre_import_validator import validate_csv
from src.schema_validator import ensure_staging_table


# ----------------------------- Unit tier -------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    "value,type_,expected",
    [
        ("1", "integer", 1),
        ("1.0", "integer", 1),
        ("true", "boolean", True),
        ("FALSE", "boolean", False),
        ("hello", "text", "hello"),
        (None, "text", None),
        ("", "integer", None),
    ],
)
def test_normalize(value, type_, expected):
    """Parametrized contract for _normalize(value, type_): covers int coercion from strings, bool from strings, and None for empty/None inputs."""
    assert _normalize(value, type_) == expected


# --------- Regression tests for BUG-04 and BUG-14 ---------------------------

@pytest.mark.unit
def test_bug04_numeric_decimal_vs_float_compare_equal():
    """A Decimal('1250.50') from the DB equals a float 1250.50 from config."""
    from decimal import Decimal
    assert _normalize(Decimal("1250.50"), "numeric") == _normalize(1250.50, "numeric")
    assert _normalize("1250.50", "numeric") == _normalize(1250.5, "numeric")


@pytest.mark.unit
def test_bug04_integer_string_vs_int_compare_equal():
    assert _normalize("42", "integer") == _normalize(42, "integer")


@pytest.mark.unit
def test_bug14_date_iso_string_vs_date_object():
    """ISO date string and a datetime.date with the same value compare equal."""
    import datetime as dt
    assert _normalize("2024-01-15", "date") == _normalize(dt.date(2024, 1, 15), "date")


@pytest.mark.unit
def test_bug14_timestamp_with_z_suffix():
    """ISO timestamp with Z suffix parses to a datetime."""
    import datetime as dt
    out = _normalize("2024-01-15T12:00:00Z", "timestamp")
    assert isinstance(out, dt.datetime)
    assert out.year == 2024 and out.hour == 12


@pytest.mark.unit
def test_bug14_uuid_string_vs_uuid_object():
    import uuid
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert _normalize(str(u), "uuid") == _normalize(u, "uuid")


@pytest.mark.unit
def test_bug14_uncoercible_value_falls_back_to_string():
    """Bad numeric input falls back to string compare instead of raising."""
    assert _normalize("not-a-number", "integer") == "not-a-number"


# ------------------------ Integration tier (DB) ------------------------------

@pytest.mark.integration
def test_integrity_passes_on_clean_load(
    pg_conn, users_job, fresh_target_table
):
    """Given fresh_target_table + a clean staging load from users.csv, all integrity checks should pass."""
    ensure_staging_table(pg_conn, users_job)
    csv_rows, staging_rows = load_csv_to_staging(pg_conn, users_job)

    _, csv_df = validate_csv(users_job)
    result = run_integrity_checks(pg_conn, users_job, csv_df, staging_rows)

    assert csv_rows == staging_rows
    failed = [c for c in result.checks if not c.passed]
    assert result.passed, f"Failures: {[(c.name, c.detail) for c in failed]}"


@pytest.mark.integration
def test_integrity_flags_duplicate_pk(
    pg_conn, users_job, fresh_target_table
):
    """Given staging loaded from CSV, then a duplicate id=1 row injected, the no_duplicate_pk check should fail."""
    ensure_staging_table(pg_conn, users_job)
    load_csv_to_staging(pg_conn, users_job)

    # Inject a duplicate id directly into staging
    with pg_conn.cursor() as cur:
        cur.execute(
            f'INSERT INTO "{users_job.staging_table}" '
            f'(id, email, full_name, signup_date, country, lifetime_value) '
            f"VALUES (1, 'dup@example.com', 'Dup', '2024-01-01', 'US', 0)"
        )
        cur.execute(f'SELECT COUNT(*) FROM "{users_job.staging_table}"')
        rows = cur.fetchone()[0]
    pg_conn.commit()

    _, csv_df = validate_csv(users_job)
    result = run_integrity_checks(pg_conn, users_job, csv_df, rows)
    assert not result.passed
    assert any(
        c.name == "no_duplicate_pk" and not c.passed for c in result.checks
    )


@pytest.mark.integration
def test_integrity_flags_missing_required_value(
    pg_conn, users_job, fresh_target_table
):
    """Given staging loaded from CSV, then email nulled on id=1, the db_not_null.email check should fail."""
    ensure_staging_table(pg_conn, users_job)
    load_csv_to_staging(pg_conn, users_job)

    # Null out a required column on one row
    with pg_conn.cursor() as cur:
        cur.execute(
            f'UPDATE "{users_job.staging_table}" '
            f'SET email = NULL WHERE id = 1'
        )
        cur.execute(f'SELECT COUNT(*) FROM "{users_job.staging_table}"')
        rows = cur.fetchone()[0]
    pg_conn.commit()

    _, csv_df = validate_csv(users_job)
    result = run_integrity_checks(pg_conn, users_job, csv_df, rows)

    assert not result.passed
    assert any(
        c.name == "db_not_null.email" and not c.passed for c in result.checks
    )
