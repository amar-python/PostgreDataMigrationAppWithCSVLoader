"""Concurrent uploads must leave one registry row and no partial state (#191, "F1").

(Not #178, which is also labelled F1 and is a different defect.)

The registry invariant is enforced by the database — migration 0002 adds
UNIQUE (file_hash) and UNIQUE (file_name) on csv_files — but the check-then-insert
in the upload path was not covered by any test. This drives the loader from
several threads released together by a barrier, so the requests genuinely overlap,
and repeats the race over several rounds because which interleaving wins is up to
the scheduler. Whatever the interleaving, the invariants below must hold.

Mutation check (from #191): drop the file_hash constraint and
test_identical_content_under_different_names_registers_once fails (10 of 10 runs
at ROUNDS = 40) —

    ALTER TABLE csv_uploads.csv_files DROP CONSTRAINT csv_files_file_hash_key;

Restore it afterwards with `ADD CONSTRAINT csv_files_file_hash_key UNIQUE (file_hash)`
(delete any duplicate rows the mutated run left first).

Only that test detects it, and that is by design: when racers share a file *name*
as well as content, UNIQUE (file_name) and the csv_<hash> table name also stop the
duplicate, so the hash constraint is not the only guard in that scenario. The
different-names scenario isolates it.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg2 import sql

from api.db import Conn
from api.services.dynamic_loader import upload_dynamic
from api.tenancy import uploads_schema

pytestmark = pytest.mark.integration

ROUNDS = 40
RACERS = 4


def _race(uploads: list[tuple[str, str]]) -> list[dict]:
    """Run each (file_name, content) upload at once; return the results in order."""
    gate = threading.Barrier(len(uploads))

    def go(item):
        gate.wait(timeout=30)
        return upload_dynamic(item[0], item[1], None, False)

    with ThreadPoolExecutor(max_workers=len(uploads)) as pool:
        return list(pool.map(go, uploads))


def _registry(names: list[str], hashes: list[str]) -> list[tuple]:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL(
            "SELECT file_name, file_hash, table_name, row_count FROM {}.csv_files "
            "WHERE file_name = ANY(%s) OR file_hash = ANY(%s)").format(sql.Identifier(uploads_schema())),
            (names, hashes))
        return cur.fetchall()


def _tables(prefixes: list[str]) -> list[str]:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = ANY(%s)",
                    (uploads_schema(), prefixes))
        return sorted(r[0] for r in cur.fetchall())


def _table_rows(table: str) -> int:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(uploads_schema()), sql.Identifier(table)))
        return cur.fetchone()[0]


def _assert_rejection_is_attributable(res: dict, winner_name: str):
    """The loser is told it lost, and to whom — not a bare error or a 500."""
    assert res["status"] == "duplicate_file", res
    assert res["existingFileName"] == winner_name, res
    assert res["reason"] in ("content", "name"), res


def test_identical_file_uploaded_concurrently_registers_once(live_api, registry_cleanup, unique_tag):
    for n in range(ROUNDS):
        name = f"race_same_{unique_tag}_{n}.csv"
        content = f"a,b\n1,{unique_tag}_{n}\n2,{unique_tag}_{n}\n"
        digest = hashlib.sha256(content.encode()).hexdigest()
        registry_cleanup.append(name)

        results = _race([(name, content)] * RACERS)

        ok = [r for r in results if r["status"] == "ok"]
        rejected = [r for r in results if r["status"] != "ok"]
        assert len(ok) == 1, f"round {n}: expected exactly one winner, got {[r['status'] for r in results]}"
        assert len(rejected) == RACERS - 1
        for r in rejected:
            _assert_rejection_is_attributable(r, name)

        # One registry row; one table; and the table holds the file once, not twice.
        rows = _registry([name], [digest])
        assert len(rows) == 1, f"round {n}: registry rows {rows}"
        assert _tables([f"csv_{digest[:16]}"]) == [f"csv_{digest[:16]}"]
        assert _table_rows(f"csv_{digest[:16]}") == 2, f"round {n}: rows duplicated or lost"


def test_identical_content_under_different_names_registers_once(live_api, registry_cleanup, unique_tag):
    """The case where file_hash, not file_name, is the guard: nothing about the
    names clashes, so only the content identity can stop a second registration."""
    for n in range(ROUNDS):
        content = f"a,b\n1,{unique_tag}_{n}\n2,{unique_tag}_{n}\n"
        digest = hashlib.sha256(content.encode()).hexdigest()
        names = [f"race_hash_{unique_tag}_{n}_{i}.csv" for i in range(RACERS)]
        registry_cleanup.extend(names)

        results = _race([(nm, content) for nm in names])

        ok = [(i, r) for i, r in enumerate(results) if r["status"] == "ok"]
        assert len(ok) == 1, f"round {n}: expected exactly one winner, got {[r['status'] for r in results]}"
        winner_name = names[ok[0][0]]
        for i, r in enumerate(results):
            if i != ok[0][0]:
                _assert_rejection_is_attributable(r, winner_name)
                assert r["reason"] == "content", r

        rows = _registry(names, [digest])
        assert len(rows) == 1, f"round {n}: registry rows {rows}"
        assert rows[0][0] == winner_name
        assert _table_rows(f"csv_{digest[:16]}") == 2, f"round {n}: rows duplicated or lost"


def test_same_name_different_content_uploaded_concurrently_registers_once(live_api, registry_cleanup, unique_tag):
    for n in range(ROUNDS):
        name = f"race_name_{unique_tag}_{n}.csv"
        uploads = [(name, f"a,b\n{i},{unique_tag}_{n}_{i}\n") for i in range(RACERS)]
        digests = [hashlib.sha256(c.encode()).hexdigest() for _, c in uploads]
        registry_cleanup.append(name)

        results = _race(uploads)

        ok = [(i, r) for i, r in enumerate(results) if r["status"] == "ok"]
        assert len(ok) == 1, f"round {n}: expected exactly one winner, got {[r['status'] for r in results]}"
        winner = ok[0][0]
        for i, r in enumerate(results):
            if i != winner:
                _assert_rejection_is_attributable(r, name)
                assert r["reason"] == "name", r

        rows = _registry([name], digests)
        assert len(rows) == 1, f"round {n}: registry rows {rows}"
        assert rows[0][1] == digests[winner], "registry holds a different upload than the winner"

        # No partial state: only the winner's table exists. A loser's table
        # (created before its registry insert failed) must have rolled back.
        expected = [f"csv_{digests[winner][:16]}"]
        present = _tables([f"csv_{d[:16]}" for d in digests])
        assert present == expected, f"round {n}: orphan tables {sorted(set(present) - set(expected))}"
        assert _table_rows(expected[0]) == 1
