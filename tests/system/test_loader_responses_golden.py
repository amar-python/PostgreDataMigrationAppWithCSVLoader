"""#330: the CSV loaders answer exactly as they did before they were split.

One corpus of uploads goes through ``POST /api/csv/upload``, covering every branch of both loaders. Every response, and
the registry rows the corpus leaves, must equal ``tests/snapshots/loader_responses.json`` byte for byte (keys in the
same order too). That file was recorded from the loaders as they were before #330 split them (``main`` @ 66b9738).

Only what changes from run to run is normalised: a random tag that keeps this run's files and rows apart from every
other test's (it is in each file name and in each file's cells), the content hash the log quotes (the tag changes it),
generated ids, timestamps and UUIDs.

A deliberate change to what the upload endpoint returns makes this test fail. Re-record the snapshot then, and say
why in the commit:

    LOADER_GOLDEN_UPDATE=1 python3 -m pytest tests/system/test_loader_responses_golden.py

(it writes the file and still fails, so a run that re-records can never pass by accident).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app

GOLDEN = Path(__file__).resolve().parents[1] / "snapshots" / "loader_responses.json"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CONTENT_HASH = re.compile(r"content hash [0-9a-f]{12}")  # the log names the file's hash, which the tag changes
VOLATILE = {"fileId", "uploadId", "upload_id", "matchedFileId", "ts", "id", "created_at", "csv_file_id"}


def _dyn(name: str, content: str, **kw) -> dict:
    return {"fileName": name, "content": content, "mode": "dynamic", **kw}


def _te(name: str, content: str, table: str = "organisations") -> dict:
    return {"fileName": name, "content": content, "mode": "te", "targetTable": table}


def corpus(t: str) -> list[tuple[str, dict]]:
    """``t`` is this run's tag. Every file that reaches the database carries it, so no run sees another's rows."""
    bad_many = "n,tag\n" + "".join(f"x{i},{t}\n" for i in range(10)) + f"7,{t}\n"
    return [
        ("good", _dyn(f"people_{t}.csv", f"id,name,qty\n1,a{t},5\n2,b,6\n")),
        ("same bytes again", _dyn(f"other_{t}.csv", f"id,name,qty\n1,a{t},5\n2,b,6\n")),
        ("version 2, new column, one row repeated", _dyn(f"people_{t}.csv", f"id,name,qty,extra\n1,a{t},5,\n3,c,7,z\n")),
        ("version 3, typed, one bad row", _dyn(f"people_{t}.csv", f"id,name,qty\n4,d{t},8\nx,e,9\n5,f,1.5\n",
                                               types=["int8", "text", "numeric"], typesConfirmed=True)),
        ("every row bad", _dyn(f"allbad_{t}.csv", f"n,tag\nx,{t}\ny,{t}\n", types=["int8", "text"])),
        ("ragged and short rows", _dyn(f"ragged_{t}.csv", f"a,b\n1,2,3\n4\n5,{t}\n")),
        ("in-file duplicates", _dyn(f"dupes_{t}.csv", f"a\n{t}\n{t}\n2\n")),
        ("empty", _dyn(f"empty_{t}.csv", "")),
        ("header only", _dyn(f"header_{t}.csv", "a,b\n")),
        ("blank header", _dyn(f"blank_{t}.csv", f",\n1,{t}\n")),
        ("header rename", _dyn(f"rename_{t}.csv", f"Old Name,b\n1,{t}\n",
                               headerMapping=[{"original": "Old Name", "renamed": "new_name"}])),
        ("bad header mapping", _dyn(f"rename2_{t}.csv", f"a\n{t}\n",
                                    headerMapping=[{"original": "nope", "renamed": "x"}])),
        ("type count mismatch", _dyn(f"types_{t}.csv", f"a,b\n1,{t}\n", types=["int8"])),
        ("unsupported type", _dyn(f"types2_{t}.csv", f"a\n{t}\n", types=["money"])),
        ("over the row cap", _dyn(f"big_{t}.csv", "a\n" + "".join(f"{i}\n" for i in range(60)))),
        ("error list capped", _dyn(f"capped_{t}.csv", bad_many, types=["int8", "text"])),
        ("overwrite flag", _dyn(f"people_{t}.csv", f"id,name,qty\n9,z{t},1\n", overwrite=True)),
        ("te: not a T&E table", _te(f"t0_{t}.csv", "a\n1\n", "nope")),
        ("te: empty", _te(f"t1_{t}.csv", "name\n")),
        ("te: unknown column", _te(f"t2_{t}.csv", f"name,bogus\n{t},1\n")),
        ("te: good", _te(f"orgs_{t}.csv", f"name,org_type,country\nAlpha {t},prime,AU\nBeta {t},test_unit,NZ\n")),
        ("te: CHECK violation on one row (database fallback)",
         _te(f"orgs2_{t}.csv", f"name,org_type,country\nGamma {t},prime,AU\nDelta {t},not_a_type,AU\n")),
        ("te: client-side type error", _te(f"ev_{t}.csv", f"is_active,name,org_type\nmaybe,E {t},prime\n")),
        ("te: ragged", _te(f"orgs3_{t}.csv", f"name,org_type\nZeta {t},prime,extra\n")),
        ("te: re-upload by the same name", _te(f"orgs_{t}.csv", f"name,org_type,country\nEta {t},academic,AU\n")),
        ("dynamic: an organisation-shaped dataset", _dyn(f"orgset_{t}.csv", f"name,org_type,country\nTheta {t},prime,AU\n")),
        ("te: content already a dataset", _te(f"orgs-te_{t}.csv", f"name,org_type,country\nTheta {t},prime,AU\n")),
        ("te: over the row cap", _te(f"bigte_{t}.csv", "name\n" + "".join(f"n{i}\n" for i in range(60)))),
    ]


def _normalise(obj, tag: str):
    if isinstance(obj, dict):
        return {k: ("<volatile>" if k in VOLATILE and v is not None else _normalise(v, tag)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalise(v, tag) for v in obj]
    if isinstance(obj, str):
        return CONTENT_HASH.sub("content hash <hash>", UUID.sub("<uuid>", obj.replace(tag, "<tag>")))
    return obj


@pytest.fixture
def caps(monkeypatch):
    """Small caps, so the row-cap and capped-error-list branches need only small files."""
    monkeypatch.setattr(settings, "MAX_ROWS", 50)
    monkeypatch.setattr(settings, "MAX_ROW_ERRORS_REPORTED", 3)
    monkeypatch.setattr(settings, "allow_destructive", True)  # the T&E re-upload replaces the earlier load


def _run(client: TestClient, tag: str) -> list[dict]:
    out = []
    for label, body in corpus(tag):
        res = client.post("/api/csv/upload", json=body)
        out.append({"case": label, "http": res.status_code, "body": _normalise(res.json(), tag)})
    listed = client.get("/api/csv/files")
    assert listed.status_code == 200, listed.text
    ours = [f for f in listed.json() if tag in f.get("file_name", "")]
    ours.sort(key=lambda f: (f["file_name"], f.get("table_name") or ""))
    out.append({"case": "registry rows the corpus left", "body": _normalise(ours, tag)})
    return out


def test_upload_responses_match_the_recorded_ones(caps):
    tag = "g" + uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        actual = json.dumps(_run(client, tag), indent=1, ensure_ascii=False) + "\n"

    if os.environ.get("LOADER_GOLDEN_UPDATE") == "1":
        GOLDEN.write_text(actual, encoding="utf-8")
        pytest.fail(f"re-recorded {GOLDEN.name}; check the diff, commit it, and run again without LOADER_GOLDEN_UPDATE")

    assert GOLDEN.exists(), f"{GOLDEN} is missing; record it as the module docstring says"
    expected = GOLDEN.read_text(encoding="utf-8")
    if actual != expected:
        got, want = json.loads(actual), json.loads(expected)
        first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        case = (want[first] if first < len(want) else got[first])["case"]
        pytest.fail(f"the upload endpoint answers differently from the recorded responses, first at case "
                    f"{first + 1} ({case!r}):\n  expected {json.dumps(want[first] if first < len(want) else None)[:600]}"
                    f"\n  actual   {json.dumps(got[first] if first < len(got) else None)[:600]}")


def test_the_corpus_reaches_every_branch_it_names():
    """A corpus that stops early (a 429, a 422 on every T&E file) would make the comparison above say nothing."""
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    by_case = {c["case"]: c for c in want}
    assert [c["case"] for c in want[:-1]] == [label for label, _ in corpus("t")]
    assert all(c["http"] in (200, 422) for c in want[:-1]), "a case was refused before it reached a loader"
    statuses = {c["case"]: c["body"].get("status") for c in want[:-1]}
    assert statuses["good"] == "ok" and statuses["same bytes again"] == "duplicate_file"
    assert statuses["te: good"] == "ok" and statuses["te: re-upload by the same name"] == "ok"
    fallback = by_case["te: CHECK violation on one row (database fallback)"]["body"]
    assert fallback["status"] == "error" and fallback["failedRows"] == 1 and "column" not in fallback["rowErrors"][0]
    assert by_case["te: content already a dataset"]["body"].get("existingMode") == "dynamic"
    assert by_case["error list capped"]["body"]["failedRows"] == 10
    assert len(by_case["error list capped"]["body"]["rowErrors"]) == 3
