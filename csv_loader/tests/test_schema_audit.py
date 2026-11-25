"""Unit tests for the schema validator's offline checks.

Uses a tiny fake psycopg2 connection so we can assert on validate_schema's
behaviour for BUG-06 (unconfigured NOT NULL audit) and BUG-08 (search-path
scoping) without needing a real database.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config import ColumnSpec, JobConfig, Thresholds
from src.schema_validator import validate_schema


pytestmark = pytest.mark.unit


def _job(columns: list[ColumnSpec]) -> JobConfig:
    return JobConfig(
        name="t",
        source_csv=Path("/tmp/x.csv"),
        target_table="users",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=columns,
        primary_key="id",
        spot_checks=[],
        thresholds=Thresholds(),
    )


def _fake_conn(rows):
    """Return a fake conn whose cursor returns the given rows from fetchall."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.return_value = rows

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def test_bug06_flags_unconfigured_not_null_target_column():
    """A NOT NULL target column with no default that's missing from config
    should produce a failed `unconfigured_required.<col>` check."""
    job = _job([
        ColumnSpec("id", "id", "integer", nullable=False),
    ])
    rows = [
        {"column_name": "id", "data_type": "integer", "is_nullable": "NO",
         "character_maximum_length": None, "column_default": None,
         "table_schema": "public"},
        {"column_name": "created_at", "data_type": "timestamp without time zone",
         "is_nullable": "NO", "character_maximum_length": None,
         "column_default": None, "table_schema": "public"},
    ]
    result = validate_schema(_fake_conn(rows), job)
    assert not result.passed
    assert any(
        c.name == "unconfigured_required.created_at" and not c.passed
        for c in result.checks
    )


def test_bug06_does_not_flag_unconfigured_column_with_default():
    """A NOT NULL column with a default is fine to omit from config."""
    job = _job([
        ColumnSpec("id", "id", "integer", nullable=False),
    ])
    rows = [
        {"column_name": "id", "data_type": "integer", "is_nullable": "NO",
         "character_maximum_length": None, "column_default": None,
         "table_schema": "public"},
        {"column_name": "created_at", "data_type": "timestamp without time zone",
         "is_nullable": "NO", "character_maximum_length": None,
         "column_default": "now()", "table_schema": "public"},
    ]
    result = validate_schema(_fake_conn(rows), job)
    assert all(
        c.name != "unconfigured_required.created_at" or c.passed
        for c in result.checks
    )


def test_bug06_does_not_flag_unconfigured_nullable_column():
    job = _job([
        ColumnSpec("id", "id", "integer", nullable=False),
    ])
    rows = [
        {"column_name": "id", "data_type": "integer", "is_nullable": "NO",
         "character_maximum_length": None, "column_default": None,
         "table_schema": "public"},
        {"column_name": "note", "data_type": "text", "is_nullable": "YES",
         "character_maximum_length": None, "column_default": None,
         "table_schema": "public"},
    ]
    result = validate_schema(_fake_conn(rows), job)
    assert all(
        c.name != "unconfigured_required.note"
        for c in result.checks
    )
