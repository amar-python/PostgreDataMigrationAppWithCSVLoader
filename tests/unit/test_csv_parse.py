"""Unit tests for api/services/csv_parse.py — parser, sanitiser, type inference
and value casting. No database, no network.
"""
from __future__ import annotations

import pytest

from api.services.csv_parse import (
    ALLOWED_TYPES,
    build_preview,
    cast_value,
    infer_type,
    parse_csv,
    pg_type_to_allowed_type,
    sanitize_columns,
    valid_identifier,
)

pytestmark = pytest.mark.unit


# ── parse_csv ─────────────────────────────────────────────────────────────────

class TestParseCsv:
    def test_simple_rows(self):
        """Comma-separated rows split into lists of strings."""
        assert parse_csv("a,b\n1,2\n") == [["a", "b"], ["1", "2"]]

    def test_no_trailing_newline(self):
        """The final row is kept when the file has no trailing newline."""
        assert parse_csv("a,b\n1,2") == [["a", "b"], ["1", "2"]]

    def test_empty_input_returns_no_rows(self):
        """An empty string parses to an empty list."""
        assert parse_csv("") == []

    def test_utf8_bom_is_stripped(self):
        """A leading UTF-8 BOM does not leak into the first header."""
        assert parse_csv("﻿id,name\n1,x\n")[0] == ["id", "name"]

    def test_crlf_line_endings(self):
        """Windows CRLF line endings parse the same as LF."""
        assert parse_csv("a,b\r\n1,2\r\n") == [["a", "b"], ["1", "2"]]

    def test_quoted_comma_stays_in_field(self):
        """A comma inside double quotes is data, not a delimiter."""
        assert parse_csv('a,b\n"x,y",2\n')[1] == ["x,y", "2"]

    def test_escaped_double_quote(self):
        """Two double quotes inside a quoted field decode to one."""
        assert parse_csv('a\n"say ""hi"""\n')[1] == ['say "hi"']

    def test_embedded_newline_in_quoted_field(self):
        """A newline inside quotes stays inside the field."""
        assert parse_csv('a,b\n"line1\nline2",2\n')[1] == ["line1\nline2", "2"]

    def test_trailing_blank_rows_are_dropped(self):
        """Blank rows at the end of the file are not data rows."""
        assert parse_csv("a,b\n1,2\n\n\n") == [["a", "b"], ["1", "2"]]

    def test_empty_cells_preserved(self):
        """Consecutive delimiters produce empty-string cells."""
        assert parse_csv("a,b,c\n1,,3\n")[1] == ["1", "", "3"]

    def test_unicode_content(self):
        """Non-ASCII text round-trips unchanged."""
        assert parse_csv("name\n東京\n")[1] == ["東京"]


# ── sanitize_columns / valid_identifier ──────────────────────────────────────

class TestSanitizeColumns:
    def test_lowercases_and_replaces_invalid_chars(self):
        """Headers become lowercase snake_case identifiers."""
        assert sanitize_columns(["First Name", "E-Mail"]) == ["first_name", "e_mail"]

    def test_leading_digit_gets_prefix(self):
        """Identifiers may not start with a digit."""
        assert sanitize_columns(["2024 total"]) == ["col_2024_total"]

    def test_blank_header_gets_positional_name(self):
        """An empty header is replaced by column_<n>."""
        assert sanitize_columns(["a", "", "c"]) == ["a", "column_2", "c"]

    def test_symbol_only_header_gets_positional_name(self):
        """A header with no usable characters falls back to column_<n>."""
        assert sanitize_columns(["%%%"]) == ["column_1"]

    def test_reserved_system_column_is_renamed(self):
        """_id collides with the system primary key and must be renamed."""
        out = sanitize_columns(["_id", "_row_hash", "_created_at"])
        assert "_id" not in out and "_row_hash" not in out and "_created_at" not in out

    def test_long_header_is_truncated(self):
        """Names are capped at 55 chars so a numeric suffix still fits in 63."""
        assert len(sanitize_columns(["x" * 200])[0]) == 55

    def test_duplicates_get_unique_suffixes(self):
        """Repeated headers are made unique."""
        out = sanitize_columns(["id", "id", "id"])
        assert len(set(out)) == 3

    def test_all_outputs_are_valid_identifiers(self):
        """Every sanitised name passes the identifier whitelist."""
        headers = ["Name", "", "1st", "a b c", "_id", "Ünïcødé", "x" * 80, "a-b"]
        assert all(valid_identifier(c) for c in sanitize_columns(headers))


class TestValidIdentifier:
    @pytest.mark.parametrize("name", ["a", "abc_1", "_x", "a" * 63])
    def test_accepts_safe_identifiers(self, name):
        """Lowercase letters, digits and underscores up to 63 chars are valid."""
        assert valid_identifier(name)

    @pytest.mark.parametrize("name", ["", "1a", "A", "a-b", "a b", "a;drop", "a" * 64])
    def test_rejects_unsafe_identifiers(self, name):
        """Uppercase, punctuation, leading digits and over-length names are rejected."""
        assert not valid_identifier(name)


# ── infer_type ────────────────────────────────────────────────────────────────

class TestInferType:
    @pytest.mark.parametrize(
        "values, expected",
        [
            (["1", "-2", "300"], "int8"),
            (["1.5", "2", "-3.25"], "numeric"),
            (["true", "no", "Y"], "boolean"),
            (["2024-01-31", "2023-12-01"], "date"),
            (["2024-01-31T10:00:00Z", "2024-02-01 08:30:00+10:00"], "timestamptz"),
            (["abc", "1"], "text"),
            ([], "text"),
            (["", "  "], "text"),
        ],
    )
    def test_picks_narrowest_type(self, values, expected):
        """The narrowest type that fits every non-empty value is chosen."""
        assert infer_type(values) == expected

    def test_blank_values_are_ignored(self):
        """Empty cells do not widen an otherwise-integer column to text."""
        assert infer_type(["1", "", "3"]) == "int8"

    def test_impossible_date_is_not_a_date(self):
        """2024-02-30 matches the pattern but is not a real date."""
        assert infer_type(["2024-02-30"]) != "date"

    def test_result_is_always_an_allowed_type(self):
        """infer_type never returns a type outside ALLOWED_TYPES."""
        for sample in (["1"], ["x"], ["true"], ["2024-01-01"], ["1.1"]):
            assert infer_type(sample) in ALLOWED_TYPES


# ── cast_value ────────────────────────────────────────────────────────────────

class TestCastValue:
    @pytest.mark.parametrize("col_type", ALLOWED_TYPES)
    def test_empty_cell_is_null_for_every_type(self, col_type):
        """A blank cell casts to NULL without error."""
        assert cast_value("  ", col_type) == (True, None, None)

    def test_int8_valid(self):
        """Whole numbers cast to Python int."""
        assert cast_value(" 42 ", "int8") == (True, 42, None)

    def test_int8_invalid(self):
        """A decimal is rejected for an int8 column with a readable reason."""
        ok, _, reason = cast_value("4.2", "int8")
        assert not ok and "whole number" in reason

    def test_numeric_keeps_string_precision(self):
        """Numerics are passed as strings so no float rounding occurs."""
        assert cast_value("0.1", "numeric") == (True, "0.1", None)

    def test_numeric_invalid(self):
        """Non-numeric text is rejected for a numeric column."""
        assert cast_value("1e5", "numeric")[0] is False

    @pytest.mark.parametrize("raw, expected", [("Yes", True), ("f", False), ("1", True), ("N", False)])
    def test_boolean_valid(self, raw, expected):
        """Common boolean spellings are accepted case-insensitively."""
        assert cast_value(raw, "boolean") == (True, expected, None)

    def test_boolean_invalid(self):
        """Unrecognised words are rejected for a boolean column."""
        assert cast_value("maybe", "boolean")[0] is False

    def test_date_valid_and_invalid(self):
        """Only real YYYY-MM-DD dates are accepted."""
        assert cast_value("2024-02-29", "date") == (True, "2024-02-29", None)
        assert cast_value("2023-02-29", "date")[0] is False
        assert cast_value("29/02/2024", "date")[0] is False

    def test_timestamp_without_zone_defaults_to_utc(self):
        """A naive timestamp is interpreted as UTC."""
        ok, val, _ = cast_value("2024-01-01T10:00:00", "timestamptz")
        assert ok and val.endswith("+00:00")

    def test_timestamp_z_suffix(self):
        """A trailing Z is accepted as UTC."""
        assert cast_value("2024-01-01T10:00:00Z", "timestamptz")[0] is True

    def test_timestamp_invalid(self):
        """Garbage is rejected for a timestamptz column."""
        assert cast_value("yesterday", "timestamptz")[0] is False

    def test_text_is_passed_through_raw(self):
        """Text values keep their original whitespace."""
        assert cast_value("  hi  ", "text") == (True, "  hi  ", None)


# ── pg_type_to_allowed_type ──────────────────────────────────────────────────

class TestPgTypeMapping:
    @pytest.mark.parametrize(
        "pg, expected",
        [
            ("integer", "int8"), ("BIGINT", "int8"), ("double precision", "numeric"),
            ("timestamp without time zone", "timestamptz"), ("character varying", "text"),
            ("boolean", "boolean"), ("date", "date"),
        ],
    )
    def test_known_types_map(self, pg, expected):
        """Postgres data_type names map onto the six client-validated types."""
        assert pg_type_to_allowed_type(pg) == expected

    @pytest.mark.parametrize("pg", ["uuid", "USER-DEFINED", "ARRAY", "jsonb", "", None])
    def test_unknown_types_return_none(self, pg):
        """Types we cannot validate client-side fall back to server casting."""
        assert pg_type_to_allowed_type(pg) is None


# ── build_preview ─────────────────────────────────────────────────────────────

class TestBuildPreview:
    def test_empty_file(self):
        """An empty file reports invalid_structure/empty."""
        assert build_preview("") == {"status": "invalid_structure", "reason": "empty"}

    def test_header_only(self):
        """A header with no data rows reports header_only."""
        assert build_preview("a,b\n")["reason"] == "header_only"

    def test_blank_header_row(self):
        """A blank first row reports no_columns."""
        assert build_preview(",,\n1,2,3\n")["reason"] == "no_columns"

    def test_ok_payload_shape(self):
        """A valid file returns headers, columns, types, sample rows and a row count."""
        out = build_preview("Id,Joined\n1,2024-01-01\n2,2024-01-02\n")
        assert out["status"] == "ok"
        assert out["headers"] == ["Id", "Joined"]
        assert out["columns"] == ["id", "joined"]
        assert out["inferredTypes"] == ["int8", "date"]
        assert out["totalRowsApprox"] == 2

    def test_short_rows_are_padded_and_long_rows_trimmed(self):
        """Sample rows always have exactly one cell per column."""
        out = build_preview("a,b\n1\n1,2,3\n")
        assert out["sampleRows"] == [["1", ""], ["1", "2"]]

    def test_sample_rows_are_capped(self):
        """Only the first sample_rows rows are returned."""
        text = "a\n" + "\n".join(str(i) for i in range(50)) + "\n"
        out = build_preview(text, sample_rows=5)
        assert len(out["sampleRows"]) == 5 and out["totalRowsApprox"] == 50
