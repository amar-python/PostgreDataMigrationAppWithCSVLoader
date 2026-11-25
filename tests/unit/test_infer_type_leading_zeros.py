"""#352 (CLI-06) twin: values with leading zeros must not be inferred as numbers.

A zero-padded identifier (postcode 02134, phone 0412345678, account 000123) is text. Inferred as ``int8`` it is stored as
the number 2134 and the zeros are gone for good; inferred as ``numeric`` it is stored as a number too. The CLI tool in
issue #352 has this bug; the API's own loader (``api/services/csv_parse.py``) has the same one, which these tests fix.

What must hold:
  * a column with any zero-padded whole-number value (a zero followed by another digit) is inferred as ``text``;
  * a column of ordinary numbers is unchanged: ``0``, ``10``, ``-5``, ``0.5``, ``1.10`` and ``-0.25`` still infer as
    numbers, because a single zero, or a zero before a decimal point, is not padding;
  * the preview a user confirms shows ``text`` for such a column, so the value loads as it was typed;
  * ``cast_value`` for a text column keeps the original characters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api.services import csv_parse as cp  # noqa: E402


@pytest.mark.parametrize(
    "values",
    [
        ["007", "012", "100"],  # the leading zero is on some values only
        ["02134", "90210"],  # US postcode
        ["0412345678", "0498765432"],  # AU mobile numbers
        ["000123", "000124"],  # padded account numbers
        ["00", "01"],
        ["-007", "5"],  # a sign does not hide the padding
        ["007.5", "1.5"],  # padding before a decimal part is still padding
    ],
)
def test_a_zero_padded_whole_number_makes_the_column_text(values):
    assert cp.infer_type(values) == "text", values


@pytest.mark.parametrize(
    "values, expected",
    [
        (["0"], "int8"),  # a single zero is a number
        (["0", "10", "-5"], "int8"),
        (["10", "100", "1000"], "int8"),  # trailing zeros are not padding
        (["0.5", "0.25"], "numeric"),  # a zero before a decimal point is not padding
        (["-0.25", "1.10"], "numeric"),
        (["1", "2", ""], "int8"),  # blanks are ignored as before
        ([], "text"),
    ],
)
def test_ordinary_numbers_are_still_numbers(values, expected):
    assert cp.infer_type(values) == expected, values


def test_the_preview_a_user_confirms_shows_text_for_a_zero_padded_column():
    csv_text = "id,postcode,amount\n1,02134,10.5\n2,90210,3\n3,00501,7.25\n"
    preview = cp.build_preview(csv_text)
    types = dict(zip(preview["headers"], preview["inferredTypes"]))
    assert types == {"id": "int8", "postcode": "text", "amount": "numeric"}, preview


def test_a_text_column_keeps_the_characters_exactly():
    assert cp.cast_value("02134", "text") == (True, "02134", None)
    assert cp.cast_value("0412345678", "text") == (True, "0412345678", None)


def test_the_bug_is_real_for_a_number_column(monkeypatch):
    """Why the inference matters: casting a padded value as a number loses the zeros, so it must never be chosen."""
    ok, value, _ = cp.cast_value("02134", "int8")
    assert ok and value == 2134 and str(value) != "02134"
