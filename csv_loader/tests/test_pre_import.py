"""Unit tests for the pre-import validator.

No database required.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config import ColumnSpec, JobConfig, Thresholds
from src.pre_import_validator import validate_csv


pytestmark = pytest.mark.unit


def _job_for(tmp_path: Path, csv_text: str, **overrides) -> JobConfig:
    """Build a synthetic job pointed at an inline CSV."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(textwrap.dedent(csv_text).lstrip(), encoding="utf-8")

    columns = overrides.pop("columns", None) or [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False, max_length=255),
        ColumnSpec("name", "name", "text", nullable=True, max_length=200),
    ]

    return JobConfig(
        name="t",
        source_csv=csv_path,
        target_table="t",
        schema_file=tmp_path / "noop.sql",
        delimiter=overrides.pop("delimiter", ","),
        encoding="utf-8",
        has_header=True,
        null_values=["", "NULL"],
        columns=columns,
        primary_key="id",
        spot_checks=[],
        thresholds=Thresholds(),
        **overrides,
    )


def test_happy_path_passes(tmp_path):
    """Given a valid 3-column CSV with clean data, validate_csv should pass all checks."""
    job = _job_for(
        tmp_path,
        """
        id,email,name
        1,a@x.com,Alice
        2,b@x.com,Bob
        """,
    )
    result, _ = validate_csv(job)
    assert result.passed, [c for c in result.checks if not c.passed]


def test_missing_file_fails_fast(tmp_path):
    """Given a job pointing at a non-existent path, validate_csv should fail the file_exists check without raising."""
    job = _job_for(tmp_path, "id,email,name\n1,a@x.com,Alice\n")
    job.source_csv = tmp_path / "does_not_exist.csv"

    result, _ = validate_csv(job)
    assert not result.passed
    assert any(c.name == "file_exists" and not c.passed for c in result.checks)


def test_missing_required_column_fails(tmp_path):
    """Given a CSV whose header omits the required 'email' column, validate_csv should fail the headers_complete check."""
    job = _job_for(
        tmp_path,
        """
        id,name
        1,Alice
        """,
    )
    result, _ = validate_csv(job)
    assert not result.passed
    assert any(
        c.name == "headers_complete" and not c.passed for c in result.checks
    )


def test_unexpected_column_flagged(tmp_path):
    """Given a CSV with an extra 'extra' header not in the job config, validate_csv should fail the no_unexpected_headers check."""
    job = _job_for(
        tmp_path,
        """
        id,email,name,extra
        1,a@x.com,Alice,oops
        """,
    )
    result, _ = validate_csv(job)
    assert not result.passed
    assert any(
        c.name == "no_unexpected_headers" and not c.passed for c in result.checks
    )


def test_null_in_required_column_fails(tmp_path):
    """Given a CSV where the non-nullable 'email' column is empty on row 1, validate_csv should fail non_null_required.email."""
    job = _job_for(
        tmp_path,
        """
        id,email,name
        1,,Alice
        2,b@x.com,Bob
        """,
    )
    result, _ = validate_csv(job)
    assert not result.passed
    assert any(
        c.name == "non_null_required.email" and not c.passed
        for c in result.checks
    )


def test_max_length_violation_flagged(tmp_path):
    """Given a CSV where 'name' exceeds its max_length of 200, validate_csv should fail max_length.name."""
    job = _job_for(
        tmp_path,
        """
        id,email,name
        1,a@x.com,""" + "z" * 250 + """
        """,
    )
    result, _ = validate_csv(job)
    assert any(
        c.name == "max_length.name" and not c.passed for c in result.checks
    )


def test_row_count_metric_present(tmp_path):
    """Given a valid 3-row CSV, the row_shape_consistent check's metric dict should record {'row_count': 3}."""
    job = _job_for(
        tmp_path,
        """
        id,email,name
        1,a@x.com,Alice
        2,b@x.com,Bob
        3,c@x.com,Carol
        """,
    )
    result, _ = validate_csv(job)
    metric_check = next(
        c for c in result.checks if c.name == "row_shape_consistent"
    )
    assert metric_check.metric == {"row_count": 3}


# --------------------- Regression tests for fixed bugs -----------------------

def test_bug01_tab_delimited_csv(tmp_path):
    """BUG-01: pandas now honors the configured delimiter."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id\temail\tname\n1\ta@x.com\tAlice\n", encoding="utf-8")
    columns = [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False, max_length=255),
        ColumnSpec("name", "name", "text", nullable=True, max_length=200),
    ]
    job = JobConfig(
        name="t", source_csv=csv_path, target_table="t",
        schema_file=tmp_path / "noop.sql",
        delimiter="\t", encoding="utf-8", has_header=True,
        null_values=["", "NULL"], columns=columns, primary_key="id",
        spot_checks=[], thresholds=Thresholds(),
    )
    result, _ = validate_csv(job)
    assert result.passed, [c for c in result.checks if not c.passed]
    headers = next(c for c in result.checks if c.name == "headers_complete")
    assert headers.passed


def test_bug02_ragged_csv_records_clean_failure(tmp_path):
    """BUG-02: a ragged CSV records a failed check instead of raising."""
    csv_path = tmp_path / "ragged.csv"
    csv_path.write_text(
        "id,email,name\n"
        "1,a@x.com,Alice\n"
        "2,b@x.com,Bob,EXTRA_COLUMN\n",
        encoding="utf-8",
    )
    columns = [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False, max_length=255),
        ColumnSpec("name", "name", "text", nullable=True, max_length=200),
    ]
    job = JobConfig(
        name="t", source_csv=csv_path, target_table="t",
        schema_file=tmp_path / "noop.sql",
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=["", "NULL"], columns=columns, primary_key="id",
        spot_checks=[], thresholds=Thresholds(),
    )
    # Must NOT raise.
    result, _ = validate_csv(job)
    assert not result.passed
    assert any(
        c.name == "row_shape_consistent" and not c.passed
        for c in result.checks
    )


def test_bug09_bom_in_first_header_is_stripped(tmp_path):
    """BUG-09: a UTF-8 file with a BOM still has the right header names."""
    csv_path = tmp_path / "bom.csv"
    csv_path.write_bytes(
        "﻿id,email,name\n1,a@x.com,Alice\n".encode("utf-8")
    )
    job = _job_for(tmp_path, "id,email,name\n1,a@x.com,Alice\n")
    job.source_csv = csv_path
    result, _ = validate_csv(job)
    assert result.passed, [c for c in result.checks if not c.passed]


def test_bug10_sniffer_mismatch_does_not_fail_stage(tmp_path):
    """BUG-10: a sniffer/config delimiter disagreement is informational."""
    # Tab-delimited file but config also says tab — sniffer might
    # mis-detect on a tiny file. The stage should still pass.
    csv_path = tmp_path / "data.tsv"
    csv_path.write_text("id\temail\tname\n1\ta@x.com\tAlice\n", encoding="utf-8")
    columns = [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False, max_length=255),
        ColumnSpec("name", "name", "text", nullable=True, max_length=200),
    ]
    job = JobConfig(
        name="t", source_csv=csv_path, target_table="t",
        schema_file=tmp_path / "noop.sql",
        delimiter="\t", encoding="utf-8", has_header=True,
        null_values=["", "NULL"], columns=columns, primary_key="id",
        spot_checks=[], thresholds=Thresholds(),
    )
    result, _ = validate_csv(job)
    delimiter_check = next(
        c for c in result.checks if c.name == "delimiter_match"
    )
    assert delimiter_check.passed  # informational, never fails


def test_bug20_min_rows_threshold_flags_empty_csv(tmp_path):
    """BUG-20: an empty (header-only) CSV fails when min_rows > 0."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("id,email,name\n", encoding="utf-8")
    columns = [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False, max_length=255),
        ColumnSpec("name", "name", "text", nullable=True, max_length=200),
    ]
    job = JobConfig(
        name="t", source_csv=csv_path, target_table="t",
        schema_file=tmp_path / "noop.sql",
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=["", "NULL"], columns=columns, primary_key="id",
        spot_checks=[],
        thresholds=Thresholds(min_rows=1),
    )
    result, _ = validate_csv(job)
    assert not result.passed
    assert any(c.name == "min_rows" and not c.passed for c in result.checks)


def test_bug20_min_rows_disabled_by_default(tmp_path):
    """When min_rows is 0 (default), an empty CSV passes pre-import."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("id,email,name\n", encoding="utf-8")
    job = _job_for(tmp_path, "id,email,name\n")  # empty after lstrip
    job.source_csv = csv_path
    job.thresholds = Thresholds(min_rows=0)
    result, _ = validate_csv(job)
    assert result.passed, [c for c in result.checks if not c.passed]
