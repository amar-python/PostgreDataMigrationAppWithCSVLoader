"""The preview parses only the head of a large file (M7, #111; decision 8: first preview page under 2 s).

The fast path must give the same preview as parsing the whole file, except that the row count is the
approximation its name says. No database, no network.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pytest

from api.services import csv_parse
from api.services.csv_parse import build_preview, parse_csv


def reference_preview(text: str, sample_rows: int = 10, infer_rows: int = 200) -> dict:
    """The preview as it was before M7: parse everything, then slice."""
    with patch.object(csv_parse, "_FAST_PREVIEW_CHARS", 10 ** 12):
        return build_preview(text, sample_rows, infer_rows)


def big(rows: int, tail: str = "") -> str:
    return "id,name,amount,when\n" + "".join(f"{i},Name {i},{i}.5,2026-01-{i % 28 + 1:02d}\n" for i in range(rows)) + tail


@pytest.mark.unit
class FastPreview(unittest.TestCase):
    def assertSamePreview(self, text: str, exact_count: bool = True):
        fast, slow = build_preview(text), reference_preview(text)
        count = (fast.pop("totalRowsApprox"), slow.pop("totalRowsApprox"))
        self.assertEqual(fast, slow)
        if exact_count:
            self.assertEqual(*count)
        return count

    def test_a_large_file_gives_the_same_preview_and_count(self):
        text = big(20_000)
        self.assertGreater(len(text), csv_parse._FAST_PREVIEW_CHARS)
        self.assertEqual(self.assertSamePreview(text), (20_000, 20_000))

    def test_it_really_stops_early(self):
        text = big(20_000)
        with patch.object(csv_parse, "parse_csv", wraps=parse_csv) as spy:
            build_preview(text)
        spy.assert_called_once_with(text, max_rows=201)

    def test_quoted_commas_quotes_and_newlines_in_the_head_are_parsed_properly(self):
        head = 'id,note\n1,"has, comma"\n2,"has ""quotes"""\n3,"two\nlines"\n'
        text = head + "".join(f"{i},plain {i}\n" for i in range(4, 20_000))
        fast = build_preview(text)
        self.assertEqual(fast["sampleRows"][:3], [["1", "has, comma"], ["2", 'has "quotes"'], ["3", "two\nlines"]])
        self.assertEqual(fast["totalRowsApprox"], 19_999)
        self.assertSamePreview(text)

    def test_a_file_that_ends_in_blank_lines_matches_the_full_parse(self):
        # The head is real rows, then thousands of blank lines: a full parse drops them, so the fast path must too.
        text = big(150, tail="\n" * 250_000)
        self.assertGreater(len(text), csv_parse._FAST_PREVIEW_CHARS)
        with patch.object(csv_parse, "parse_csv", wraps=parse_csv) as spy:
            self.assertEqual(self.assertSamePreview(text, exact_count=False)[0], 150)
        self.assertIn(((text,), {}), [(c.args, c.kwargs) for c in spy.call_args_list],
                      "the head ended in blank lines, so the whole file is parsed")

    def test_a_head_that_ends_in_blank_lines_falls_back_to_the_full_parse(self):
        text = big(5) + "\n" * 250_000 + big(10)[len("id,name,amount,when\n"):]
        self.assertGreater(len(text), csv_parse._FAST_PREVIEW_CHARS)
        self.assertSamePreview(text, exact_count=False)

    def test_blank_lines_after_a_long_file_are_not_counted_as_rows(self):
        text = big(20_000, tail="\n" * 100)
        self.assertEqual(self.assertSamePreview(text), (20_000, 20_000))

    def test_a_short_file_below_the_threshold_is_unchanged(self):
        for text in ("a,b\n1,2\n", "a,b\n", "", "a,b\n\n\n", "﻿a,b\n1,2\n"):
            self.assertEqual(build_preview(text), reference_preview(text), repr(text))

    def test_header_only_and_empty_large_files_still_report_their_structure(self):
        self.assertEqual(build_preview("h," * 100_000 + "h\n")["reason"], "header_only")

    def test_crlf_line_endings(self):
        text = big(20_000).replace("\n", "\r\n")
        self.assertEqual(self.assertSamePreview(text), (20_000, 20_000))

    def test_parse_csv_max_rows_returns_the_first_rows_only(self):
        self.assertEqual(parse_csv("a,b\n1,2\n3,4\n5,6\n", max_rows=2), [["a", "b"], ["1", "2"]])
        self.assertEqual(parse_csv("a,b\n1,2\n", max_rows=10), [["a", "b"], ["1", "2"]])
        self.assertEqual(len(parse_csv("a\n1\n2\n")), 3)
