# -*- coding: utf-8 -*-
"""Edge-case stress tests for the pre-import validation pipeline.

Each test constructs a JobConfig pointing at a synthetic CSV in
input_data/edge_cases/ and exercises validate_csv against it.
No database required — these are pure CSV-side validation tests.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import ColumnSpec, JobConfig, Thresholds
from src.pre_import_validator import validate_csv

pytestmark = pytest.mark.unit

EDGE = ROOT / "input_data" / "edge_cases"


def _base_job(**overrides) -> JobConfig:
    """Return a users-shaped JobConfig with optional overrides."""
    defaults = dict(
        name="edge_test",
        source_csv=EDGE / "users_bom.csv",
        target_table="users",
        schema_file=ROOT / "input_data" / "users_schema.sql",
        delimiter=",",
        encoding="utf-8",
        has_header=True,
        null_values=["", "NULL", "N/A", "null"],
        columns=[
            ColumnSpec("id", "id", "integer", nullable=False),
            ColumnSpec("email", "email", "text", nullable=False, max_length=255),
            ColumnSpec("full_name", "full_name", "text", nullable=False, max_length=200),
            ColumnSpec("signup_date", "signup_date", "date", nullable=False),
            ColumnSpec("country", "country", "text", nullable=True, max_length=2),
            ColumnSpec("lifetime_value", "lifetime_value", "numeric", nullable=True),
        ],
        primary_key="id",
        thresholds=Thresholds(min_rows=1),
    )
    defaults.update(overrides)
    return JobConfig(**defaults)


# ---------------------------------------------------------------------------
# 1. BOM handling
# ---------------------------------------------------------------------------

class TestBOM:
    def test_bom_csv_strips_header_correctly(self):
        job = _base_job(source_csv=EDGE / "users_bom.csv")
        stage, df = validate_csv(job)
        assert stage.passed
        assert "id" in df.columns
        assert not any(c.startswith("﻿") for c in df.columns)

    def test_bom_csv_row_count(self):
        job = _base_job(source_csv=EDGE / "users_bom.csv")
        stage, df = validate_csv(job)
        assert len(df) == 3


# ---------------------------------------------------------------------------
# 2. Tab-delimited
# ---------------------------------------------------------------------------

class TestTabDelimited:
    def test_tab_csv_passes_with_correct_delimiter(self):
        job = _base_job(source_csv=EDGE / "users_tab.tsv", delimiter="\t")
        stage, df = validate_csv(job)
        assert stage.passed
        assert len(df) == 3

    def test_tab_csv_fails_with_wrong_delimiter(self):
        job = _base_job(source_csv=EDGE / "users_tab.tsv", delimiter=",")
        stage, df = validate_csv(job)
        headers_check = next(
            (c for c in stage.checks if c.name == "headers_complete"), None
        )
        assert headers_check is not None
        assert not headers_check.passed


# ---------------------------------------------------------------------------
# 3. Duplicate primary keys
# ---------------------------------------------------------------------------

class TestDuplicates:
    def test_dupes_csv_parses_successfully(self):
        job = _base_job(source_csv=EDGE / "users_dupes.csv")
        stage, df = validate_csv(job)
        assert stage.passed
        assert len(df) == 5

    def test_dupes_csv_has_duplicate_ids(self):
        job = _base_job(source_csv=EDGE / "users_dupes.csv")
        _, df = validate_csv(job)
        assert df["id"].duplicated().sum() == 2


# ---------------------------------------------------------------------------
# 4. Empty CSV (header only)
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_csv_fails_min_rows(self):
        job = _base_job(
            source_csv=EDGE / "users_empty.csv",
            thresholds=Thresholds(min_rows=1),
        )
        stage, df = validate_csv(job)
        min_check = next(
            (c for c in stage.checks if c.name == "min_rows"), None
        )
        assert min_check is not None
        assert not min_check.passed

    def test_empty_csv_passes_when_min_rows_disabled(self):
        job = _base_job(
            source_csv=EDGE / "users_empty.csv",
            thresholds=Thresholds(min_rows=0),
        )
        stage, df = validate_csv(job)
        min_check = next(
            (c for c in stage.checks if c.name == "min_rows"), None
        )
        assert min_check is None


# ---------------------------------------------------------------------------
# 5. Unicode-heavy data
# ---------------------------------------------------------------------------

class TestUnicode:
    def test_unicode_csv_parses_all_rows(self):
        job = _base_job(source_csv=EDGE / "users_unicode.csv")
        stage, df = validate_csv(job)
        assert stage.passed
        assert len(df) == 6

    def test_unicode_names_preserved(self):
        job = _base_job(source_csv=EDGE / "users_unicode.csv")
        _, df = validate_csv(job)
        names = df["full_name"].tolist()
        assert "Hans Müller" in names
        assert "José María Ñoño" in names
        assert "田中太郎" in names
        assert "李小明" in names
        assert "Åke Svensson" in names
        assert "Łukasz Kowalski" in names

    def test_unicode_country_within_max_length(self):
        job = _base_job(source_csv=EDGE / "users_unicode.csv")
        stage, _ = validate_csv(job)
        length_check = next(
            (c for c in stage.checks if c.name == "max_length.country"), None
        )
        assert length_check is not None
        assert length_check.passed


# ---------------------------------------------------------------------------
# 6. Null-heavy data (nulls in required columns)
# ---------------------------------------------------------------------------

class TestNulls:
    def test_nulls_csv_flags_required_columns(self):
        job = _base_job(source_csv=EDGE / "users_nulls.csv")
        stage, df = validate_csv(job)
        assert not stage.passed

    def test_nulls_in_email_detected(self):
        job = _base_job(source_csv=EDGE / "users_nulls.csv")
        stage, _ = validate_csv(job)
        email_check = next(
            (c for c in stage.checks if c.name == "non_null_required.email"),
            None,
        )
        assert email_check is not None
        assert not email_check.passed

    def test_nulls_in_full_name_detected(self):
        job = _base_job(source_csv=EDGE / "users_nulls.csv")
        stage, _ = validate_csv(job)
        name_check = next(
            (c for c in stage.checks if c.name == "non_null_required.full_name"),
            None,
        )
        assert name_check is not None
        assert not name_check.passed

    def test_nulls_in_signup_date_detected(self):
        job = _base_job(source_csv=EDGE / "users_nulls.csv")
        stage, _ = validate_csv(job)
        date_check = next(
            (c for c in stage.checks
             if c.name == "non_null_required.signup_date"),
            None,
        )
        assert date_check is not None
        assert not date_check.passed


# ---------------------------------------------------------------------------
# 7. Special characters (commas, quotes, tabs in quoted fields)
# ---------------------------------------------------------------------------

class TestSpecialChars:
    def test_special_chars_csv_parses(self):
        job = _base_job(source_csv=EDGE / "users_special_chars.csv")
        stage, df = validate_csv(job)
        assert stage.passed
        assert len(df) == 5

    def test_embedded_comma_preserved(self):
        job = _base_job(source_csv=EDGE / "users_special_chars.csv")
        _, df = validate_csv(job)
        assert "Anderson, Alice" in df["full_name"].tolist()

    def test_embedded_quotes_preserved(self):
        job = _base_job(source_csv=EDGE / "users_special_chars.csv")
        _, df = validate_csv(job)
        assert 'Brown, Robert "Bob"' in df["full_name"].tolist()

    def test_apostrophe_preserved(self):
        job = _base_job(source_csv=EDGE / "users_special_chars.csv")
        _, df = validate_csv(job)
        assert "O'Brien, Carol" in df["full_name"].tolist()


# ---------------------------------------------------------------------------
# 8. Ragged rows (inconsistent column counts)
# ---------------------------------------------------------------------------

class TestRagged:
    def test_ragged_csv_fails_row_shape(self):
        job = _base_job(source_csv=EDGE / "users_ragged.csv")
        stage, df = validate_csv(job)
        shape_check = next(
            (c for c in stage.checks if c.name == "row_shape_consistent"),
            None,
        )
        assert shape_check is not None
        assert not shape_check.passed

    def test_ragged_csv_returns_no_dataframe(self):
        job = _base_job(source_csv=EDGE / "users_ragged.csv")
        _, df = validate_csv(job)
        assert df is None


# ---------------------------------------------------------------------------
# 9. Wrong headers
# ---------------------------------------------------------------------------

class TestWrongHeaders:
    def test_wrong_headers_flags_missing(self):
        job = _base_job(source_csv=EDGE / "users_wrong_headers.csv")
        stage, _ = validate_csv(job)
        headers_check = next(
            (c for c in stage.checks if c.name == "headers_complete"), None
        )
        assert headers_check is not None
        assert not headers_check.passed
        assert "Missing" in headers_check.detail

    def test_wrong_headers_flags_unexpected(self):
        job = _base_job(source_csv=EDGE / "users_wrong_headers.csv")
        stage, _ = validate_csv(job)
        extra_check = next(
            (c for c in stage.checks if c.name == "no_unexpected_headers"),
            None,
        )
        assert extra_check is not None
        assert not extra_check.passed


# ---------------------------------------------------------------------------
# 10. Over-length values (country > 2 chars)
# ---------------------------------------------------------------------------

class TestOverlength:
    def test_overlength_country_detected(self):
        job = _base_job(source_csv=EDGE / "users_overlength.csv")
        stage, _ = validate_csv(job)
        len_check = next(
            (c for c in stage.checks if c.name == "max_length.country"), None
        )
        assert len_check is not None
        assert not len_check.passed
        assert "3" in len_check.detail or "violations" in len_check.detail


# ---------------------------------------------------------------------------
# 11. Large CSV (10,000 rows)
# ---------------------------------------------------------------------------

class TestLargeCSV:
    def test_large_csv_parses_all_rows(self):
        job = _base_job(source_csv=EDGE / "users_large.csv")
        stage, df = validate_csv(job)
        row_check = next(
            (c for c in stage.checks if c.name == "row_shape_consistent"),
            None,
        )
        assert row_check is not None
        assert row_check.passed
        assert len(df) == 10000

    def test_large_csv_passes_min_rows(self):
        job = _base_job(
            source_csv=EDGE / "users_large.csv",
            thresholds=Thresholds(min_rows=5000),
        )
        stage, _ = validate_csv(job)
        min_check = next(
            (c for c in stage.checks if c.name == "min_rows"), None
        )
        assert min_check is not None
        assert min_check.passed

    def test_large_csv_performance(self):
        """Validation of 10k rows should complete in under 5 seconds."""
        import time
        job = _base_job(source_csv=EDGE / "users_large.csv")
        start = time.perf_counter()
        stage, df = validate_csv(job)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"Validation took {elapsed:.2f}s (limit: 5s)"


# ---------------------------------------------------------------------------
# 12. Missing file
# ---------------------------------------------------------------------------

class TestMissingFile:
    def test_nonexistent_csv_fails_cleanly(self):
        job = _base_job(source_csv=EDGE / "does_not_exist.csv")
        stage, df = validate_csv(job)
        assert not stage.passed
        assert df is None
        file_check = next(
            (c for c in stage.checks if c.name == "file_exists"), None
        )
        assert file_check is not None
        assert not file_check.passed
