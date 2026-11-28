"""scripts/sample_verification_run.py (#59): a database that is not fresh stops the run cleanly.

On a populated database the first upload is refused as a duplicate, so the response has no table in it. The
script used to die with `KeyError: 'tableName'` and a traceback; it now says the database is not fresh, exits
2 (cannot run, as for a missing password) and writes nothing, so the committed sample report is never
overwritten by a half run. No server or database is needed: the API and the connection are stubs.
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import sample_verification_run as run

pytestmark = [pytest.mark.unit, pytest.mark.regression]

DUPLICATE = {"status": "duplicate_file", "reason": "content", "existingFileName": "orgs_sample.csv"}


def _result(response: dict, http: int = 200) -> dict:
    return {"http": http, "preview": {}, "response": response}


def test_a_refused_upload_stops_with_the_reason_and_the_way_out():
    with pytest.raises(run.NotFresh) as info:
        run.loaded_table(_result(DUPLICATE), "orgs_sample.csv (Test and Evaluation)")

    msg = str(info.value)
    assert "orgs_sample.csv" in msg and "HTTP 200" in msg and "'duplicate_file'" in msg and "content" in msg
    assert "FRESH database" in msg and "Nothing was written" in msg


def test_a_loaded_upload_gives_its_table():
    assert (
        run.loaded_table(_result({"status": "ok", "tableName": "tenant_dev.organisations"}), "x")
        == "tenant_dev.organisations"
    )


@pytest.mark.parametrize(
    "response, shown",
    [
        ({"status": "error", "message": "a plain message"}, "a plain message"),
        ({"status": "invalid_structure", "reason": "empty"}, "empty"),
        ({"detail": "File too large"}, "File too large"),
        ({}, "no reason given"),
    ],
)
def test_whatever_the_refusal_looks_like_it_is_explained(response, shown):
    with pytest.raises(run.NotFresh, match=shown):
        run.loaded_table(_result(response, 413), "file")


class StubApi:
    """Signs in, then refuses every upload as a duplicate: what a populated database does."""

    def __init__(self, base):
        self.token = None

    def call(self, method, path, body=None):
        if path == "/api/auth/login":
            return 200, {"token": "t"}
        if path == "/api/health":
            return 200, {"status": "ok"}
        if path == "/api/csv/preview":
            return 200, {"status": "ok", "inferredTypes": ["text"], "teTableMatch": "organisations"}
        if path == "/api/csv/upload":
            return 200, dict(DUPLICATE)
        raise AssertionError(f"unexpected call {method} {path}")


def test_collect_stops_before_touching_the_database_when_the_first_upload_is_refused():
    conn = MagicMock()

    with pytest.raises(run.NotFresh):
        run.collect(StubApi("x"), conn)

    conn.cursor.return_value.execute.assert_not_called()


def test_main_on_a_populated_database_exits_2_says_why_and_writes_nothing(tmp_path, monkeypatch, capsys):
    for name in ("orgs_sample.csv", "equipment_register.csv"):
        shutil.copy(run.SAMPLES / name, tmp_path / name)
    monkeypatch.setattr(run, "SAMPLES", tmp_path)
    monkeypatch.setattr(run, "Api", StubApi)
    monkeypatch.setattr(run.psycopg2, "connect", lambda **kw: MagicMock())
    monkeypatch.setenv("TE_ADMIN_PASSWORD", "x" * 12)
    monkeypatch.setattr(sys, "argv", ["sample_verification_run.py"])

    code = run.main()

    assert code == 2
    err = capsys.readouterr().err
    assert "FRESH database" in err and "Traceback" not in err
    assert sorted(p.name for p in Path(tmp_path).iterdir()) == ["equipment_register.csv", "orgs_sample.csv"], (
        "no report or evidence file was written"
    )
