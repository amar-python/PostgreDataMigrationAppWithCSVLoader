"""#352 (CLI-06): auto_migrate must not turn zero-padded identifiers into numbers.

``auto_migrate.py`` guesses each column's type from the data. Postcodes such as ``0800`` (Darwin), phone numbers such as
``0412345678`` and account numbers were read as numbers and became ``INTEGER``, so ``0800`` was stored as ``800`` for
good. The comparison step turns both sides into numbers for a numeric column, so ``800 == 800`` passed and no failure was
reported. (``_is_integer`` alone is not enough: the value would then be accepted by ``_is_numeric`` and become
``NUMERIC(18,2)`` 800.00.) The API's own loader had the same bug (fixed in #395).

What must hold:
  * a column of numbers where any value has a zero followed by another digit is inferred as ``text``;
  * ordinary numbers are unchanged: ``0``, ``10``, ``-5`` stay integers, ``0.5``, ``-0.25`` and ``1250.50`` stay
    numeric, and a column of only ``0`` and ``1`` is still boolean;
  * the whole path keeps the value: auto_migrate loads a file of postcodes and phone numbers and the database holds
    ``'0800'`` and ``'0412345678'``;
  * for a text column the comparison step does not treat ``0800`` and ``800`` as equal.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

import auto_migrate
from src.integrity_checks import _normalize


@pytest.mark.unit
@pytest.mark.parametrize("values", [
    ["0800", "2000"],                  # the example in the issue: a Darwin postcode and another
    ["0412345678", "0498765432"],      # phone numbers
    ["000123", "000124"],              # padded account numbers
    ["007", "12", "100"],              # padding on one value is enough
    ["-007", "5"],                     # a sign does not hide it
    ["007.5", "1.5"],                  # padding before a decimal part
])
def test_a_zero_padded_number_makes_the_column_text(values):
    assert auto_migrate.infer_column_type(pd.Series(values)) == "text", values


@pytest.mark.unit
@pytest.mark.parametrize("values, expected", [
    (["0", "10"], "integer"),
    (["10", "-5"], "integer"),
    (["10", "100", "1000"], "integer"),        # trailing zeros are not padding
    (["0.5", "10"], "numeric"),
    (["-0.25", "1.10"], "numeric"),
    (["1250.50", "0.00"], "numeric"),
    (["0", "1", "0", "1"], "boolean"),         # a 0/1 column is still a boolean
])
def test_ordinary_numbers_are_still_numbers(values, expected):
    assert auto_migrate.infer_column_type(pd.Series(values)) == expected, values


@pytest.mark.unit
def test_blank_values_are_ignored_when_looking_for_padding():
    assert auto_migrate.infer_column_type(pd.Series(["0800", None, "2000"])) == "text"
    assert auto_migrate.infer_column_type(pd.Series(["10", None, "2000"])) == "integer"


@pytest.mark.unit
def test_a_text_column_of_postcodes_is_wide_enough_and_gets_a_varchar():
    series = pd.Series(["0800", "2000"])
    col_type = auto_migrate.infer_column_type(series)
    assert col_type == "text" and auto_migrate.infer_max_length(series, col_type) >= 4
    sql = auto_migrate.generate_schema_sql("t", [{"db_column": "postcode", "type": "text", "nullable": True, "max_length": 20}],
                                           "postcode")
    assert "VARCHAR(20)" in sql


@pytest.mark.unit
def test_the_comparison_step_does_not_treat_0800_and_800_as_equal_for_a_text_column():
    assert _normalize("0800", "text") != _normalize("800", "text")
    assert _normalize("0800", "text") == _normalize(" 0800 ", "text"), "only surrounding whitespace is ignored"
    assert _normalize("0800", "integer") == _normalize("800", "integer"), "(why the column type must not be integer)"


@pytest.fixture
def tool_folder(tmp_path, monkeypatch, pg_conn):
    """auto_migrate working in a temporary folder (config.yaml + input_data/), with the probe table cleaned up."""
    (tmp_path / "input_data").mkdir()
    config = tmp_path / "config.yaml"
    shutil.copy(Path(__file__).resolve().parents[1] / "config.yaml", config)   # the shipped jobs, so `jobs:` is not empty
    monkeypatch.setattr(auto_migrate, "CONFIG_PATH", config)
    monkeypatch.setattr(auto_migrate, "INPUT_DIR", tmp_path / "input_data")

    def drop():
        pg_conn.rollback()
        with pg_conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "cli06_postcodes_staging" CASCADE')
            cur.execute('DROP TABLE IF EXISTS "cli06_postcodes" CASCADE')
        pg_conn.commit()
    drop()
    yield tmp_path
    drop()


@pytest.mark.integration
def test_postcodes_and_phone_numbers_round_trip_through_auto_migrate_with_their_zeros(pg_conn, tool_folder):
    csv = tool_folder / "input_data" / "cli06_postcodes.csv"
    csv.write_text("id,postcode,phone,amount\n"
                   "1,0800,0412345678,10.50\n"
                   "2,2000,0498765432,3.00\n"
                   "3,0200,0455555555,7.25\n", encoding="utf-8")
    assert auto_migrate.auto_migrate(csv) == 0, "auto_migrate reported a failure"
    with pg_conn.cursor() as cur:
        cur.execute("SELECT postcode, phone FROM cli06_postcodes ORDER BY id")
        assert cur.fetchall() == [("0800", "0412345678"), ("2000", "0498765432"), ("0200", "0455555555")]
        cur.execute("SELECT data_type FROM information_schema.columns WHERE table_name = 'cli06_postcodes' "
                    "ORDER BY ordinal_position")
        assert [r[0] for r in cur.fetchall()] == ["integer", "character varying", "character varying", "numeric"]
