"""#330: the pieces the CSV loaders were split into, tested without a database.

Before the split these lived inside two functions of 277 and 263 lines, so every one of them needed a full system test
against PostgreSQL. The system tests (tests/system/) still cover the loaders end to end.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from api.config import settings
from api.services import dynamic_loader as dyn
from api.services import load_common as lc
from api.services import te_loader as te

pytestmark = pytest.mark.unit


# ── load_common ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_log_adds_a_count_only_when_given():
    logs: list[dict] = []
    lc.log(logs, "parse", "Parsed 3 rows", count=3)
    lc.log(logs, "error", "bad", "error")
    assert [(e["step"], e["level"], e["message"], e.get("count")) for e in logs] == [
        ("parse", "info", "Parsed 3 rows", 3),
        ("error", "error", "bad", None),
    ]
    assert "count" not in logs[1] and all(isinstance(e["ts"], int) for e in logs)


def test_row_errors_count_every_failure_but_keep_only_the_cap(monkeypatch):
    monkeypatch.setattr(settings, "MAX_ROW_ERRORS_REPORTED", 2)
    errors = lc.RowErrors()
    for n in range(1, 6):
        errors.add(n, "qty", "x", "not a number")
    errors.add_db_error(6, "violates foreign key")
    assert errors.failed == 6
    assert errors.items == [
        {"rowNumber": 1, "column": "qty", "value": "x", "reason": "not a number"},
        {"rowNumber": 2, "column": "qty", "value": "x", "reason": "not a number"},
    ]
    assert errors.first() == errors.items[0]


def test_a_database_row_error_names_no_column():
    errors = lc.RowErrors()
    errors.add_db_error(4, "duplicate key value")
    assert errors.items == [{"rowNumber": 4, "reason": "duplicate key value"}] and errors.first()["rowNumber"] == 4
    assert lc.RowErrors().first() is None


def test_a_row_with_cells_beyond_the_header_is_an_error():
    errors = lc.RowErrors()
    assert lc.ragged(["a", "b"], 2, 1, errors) is False
    assert lc.ragged(["a", "b", "extra"], 2, 2, errors) is True
    assert errors.failed == 1
    e = errors.items[0]
    assert (e["rowNumber"], e["column"], e["value"]) == (2, "(beyond header)", "extra") and "3" in e["reason"]


def test_the_row_cap_refuses_only_files_over_it(monkeypatch):
    monkeypatch.setattr(settings, "MAX_ROWS", 3)
    logs: list[dict] = []
    assert lc.too_many_rows(3, logs) is None and logs == []
    refused = lc.too_many_rows(4, logs)
    assert refused["status"] == "error" and "at most 3" in refused["message"] and refused["logs"] is logs
    assert logs[-1]["level"] == "error"


def test_the_rows_failed_response_keeps_its_field_order():
    errors = lc.RowErrors()
    errors.add(1, "a", "x", "bad")
    logs: list[dict] = []
    res = lc.rows_failed("Nothing saved.", errors, 5, logs, insertedRows=0, columns=["a"])
    assert list(res) == ["status", "message", "rowErrors", "totalRows", "failedRows", "insertedRows", "columns", "logs"]
    assert (res["status"], res["totalRows"], res["failedRows"]) == ("error", 5, 1)
    assert logs[-1]["message"] == "Nothing saved."


def test_the_ok_result_keeps_its_field_order():
    res = lc.ok_result(7, "t", 3, 2, 1, 0, ["a"], ["text"], rowErrors=[], logs=[])
    assert res["fileId"] == "7"
    assert list(res) == [
        "status",
        "fileId",
        "tableName",
        "totalRows",
        "insertedRows",
        "duplicateRowsSkipped",
        "failedRows",
        "columns",
        "types",
        "rowErrors",
        "logs",
    ]


def _stmt(text):
    stmt = MagicMock()
    stmt.as_string.return_value = text
    return stmt


def test_a_batch_that_succeeds_is_inserted_in_one_go():
    cur = MagicMock()
    rows = [(1, ["a"]), (2, ["b"])]
    with patch.object(lc, "execute_values") as ev:
        assert lc.insert_with_row_fallback(cur, _stmt("BATCH"), _stmt("ROW"), rows, lc.RowErrors()) == 2
    ev.assert_called_once_with(cur, "BATCH", [["a"], ["b"]])
    assert [c.args[0] for c in cur.execute.call_args_list] == ["SAVEPOINT chunk_sp", "RELEASE SAVEPOINT chunk_sp"]


def test_a_failed_batch_is_retried_row_by_row_and_the_bad_row_is_recorded():
    cur = MagicMock()
    row_stmt = _stmt("ROW")

    def execute(stmt, values=None):
        if stmt is row_stmt and values == ["bad"]:
            raise Exception('insert or update violates foreign key constraint "fk"\nDETAIL: more')

    cur.execute.side_effect = execute
    errors = lc.RowErrors()
    rows = [(1, ["ok"]), (2, ["bad"]), (3, ["ok2"])]
    with patch.object(lc, "execute_values", side_effect=Exception("batch failed")):
        assert lc.insert_with_row_fallback(cur, _stmt("BATCH"), row_stmt, rows, errors) == 2
    assert errors.failed == 1
    assert errors.items == [{"rowNumber": 2, "reason": 'insert or update violates foreign key constraint "fk"'}]
    sql_run = [c.args[0] if isinstance(c.args[0], str) else "ROW" for c in cur.execute.call_args_list]
    assert sql_run[:3] == ["SAVEPOINT chunk_sp", "ROLLBACK TO SAVEPOINT chunk_sp", "RELEASE SAVEPOINT chunk_sp"]
    assert sql_run.count("ROLLBACK TO SAVEPOINT row_sp") == 1 and sql_run.count("RELEASE SAVEPOINT row_sp") == 3


def test_batches_are_chunked():
    cur = MagicMock()
    rows = [(n, [str(n)]) for n in range(1, 6)]
    with patch.object(lc, "execute_values") as ev:
        assert lc.insert_with_row_fallback(cur, _stmt("B"), _stmt("R"), rows, lc.RowErrors(), chunk_size=2) == 5
    assert [len(c.args[2]) for c in ev.call_args_list] == [2, 2, 1]


# ── dynamic loader ──────────────────────────────────────────────────────────────────────────────────────────────


def test_the_row_hash_is_unambiguous():
    """#178: a join on U+001F made these two rows hash the same."""
    assert dyn.row_hash(["a\x1fb", "c"]) != dyn.row_hash(["a", "b\x1fc"])
    expected = json.dumps(["x", "1"], ensure_ascii=False, separators=(",", ":"))
    assert dyn.row_hash(["x", "1"]).startswith("v2:") and len(dyn.row_hash([expected])) == 67


def test_dynamic_rows_are_cast_and_in_file_duplicates_skipped():
    rows = [["1", "a"], ["1", "a"], ["x", "b"], ["2"], ["3", "c", "extra"]]
    out = dyn.cast_rows(rows, ["n", "s"], ["int8", "text"])
    assert out.duplicates == 1
    assert [r[:-1] for r in out.to_insert] == [(1, "a"), (2, None)]  # a short row's missing cell is empty: NULL
    assert out.insert_rows == [1, 4]
    assert out.errors.failed == 2
    assert [(e["rowNumber"], e["column"]) for e in out.errors.items] == [(3, "n"), (5, "(beyond header)")]
    assert out.to_insert[0][-1] == dyn.row_hash(["1", "a"])


def test_the_structure_check_names_each_kind_of_empty_file():
    assert dyn._structure_problem([], [])["reason"] == "empty"
    assert dyn._structure_problem([["a"]], [])["reason"] == "header_only"
    assert dyn._structure_problem([["", " "], ["1", "2"]], [])["reason"] == "no_columns"
    assert dyn._structure_problem([["a"], ["1"]], []) is None


def test_header_renames_are_applied_or_refused():
    rows = [["Old Name", "b"], ["1", "2"]]
    logs: list[dict] = []
    renamed, refused = dyn._apply_header_mapping(rows, [{"original": "Old Name", "renamed": "new_name"}], logs)
    assert refused is None and renamed[0][0] == "new_name" and renamed[1] == ["1", "2"]
    assert logs[-1]["count"] == 1
    same, refused = dyn._apply_header_mapping(rows, None, [])
    assert same is rows and refused is None
    _, refused = dyn._apply_header_mapping(rows, [{"original": "missing", "renamed": "x"}], [])
    assert refused["reason"] == "invalid_header_mapping"


# sanitize_columns names blank headers and de-duplicates (a, A -> a, a_2), so only the types can be refused here.
@pytest.mark.parametrize(
    "header, types, message",
    [
        (["a", "b"], ["text"], "Provided 1 column types but the CSV has 2 columns."),
        (["a"], ["money"], "Unsupported column type provided."),
    ],
)
def test_unusable_columns_or_types_are_refused(header, types, message):
    res = dyn._columns_and_types(header, types, [])
    assert isinstance(res, dict) and res["status"] == "error" and message in res["message"]


def test_columns_without_types_default_to_text():
    assert dyn._columns_and_types(["Name", "Qty"], None, []) == (["name", "qty"], ["text", "text"])
    assert dyn._columns_and_types(["a"], ["int8"], []) == (["a"], ["int8"])
    assert dyn._columns_and_types(["a", "A", ""], None, []) == (["a", "a_2", "column_3"], ["text"] * 3)


def test_the_every_row_failed_message_names_the_first_problem():
    errors = lc.RowErrors()
    errors.add(2, "qty", "x", "not an integer")
    res = dyn._every_row_failed(errors, 2, ["qty"], ["int8"], [])
    assert res["message"] == (
        'None of the 2 rows could be imported, so nothing was saved. First problem: row 2, column "qty": not an integer'
    )
    assert (res["columns"], res["types"]) == (["qty"], ["int8"])


# ── T&E loader ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_te_rows_are_stripped_and_empty_cells_are_null():
    errors = lc.RowErrors()
    rows = [[" 5 ", "", " x "], ["oops", "1", "y"], ["1", "2", "3", "4"]]
    out = te.cast_te_rows(rows, ["n", "m", "u"], ["int8", "int8", None], errors)
    assert out == [(1, [5, None, "x"])]  # None type: Postgres casts the (stripped) text itself
    assert [(e["rowNumber"], e["column"]) for e in errors.items] == [(2, "n"), (3, "(beyond header)")]


def test_te_messages_say_how_many_rows_failed():
    errors = lc.RowErrors()
    errors.add_db_error(3, "violates foreign key")
    some = te._not_imported(errors, 4, "personnel", ["id"], [])
    assert some["message"].startswith("1 of the 4 rows could not be imported into personnel, so nothing was saved.")
    assert some["message"].endswith("First problem: row 3, : violates foreign key")
    assert (some["insertedRows"], some["failedRows"]) == (0, 1)
    every = te._not_imported(errors, 1, "personnel", ["id"], [])
    assert every["message"].startswith("None of the 1 rows could be imported into personnel")


def test_te_refuses_a_table_that_is_not_a_te_table_before_touching_the_database():
    res = te.upload_te("f.csv", "a\n1\n", "not_a_table")
    assert res["status"] == "error" and "is not a T&E table" in res["message"]
