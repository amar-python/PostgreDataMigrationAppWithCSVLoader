"""Concurrent uploads leave one registry row per file and no partial state (#191, "F1").

(Not #178, which is also labelled F1 and is a different defect.)

The registry invariant is enforced by the database: UNIQUE (file_hash) on csv_files,
and, since M5, a per-dataset advisory lock that serialises uploads of the same
filename. Neither was covered by a test that makes uploads genuinely overlap. This
releases several uploads together with a barrier and repeats the race over many
rounds, because which interleaving wins is up to the scheduler. Whatever the
interleaving, the invariants below must hold.

Three cases, because the guard differs:

* identical file, same name: the dataset lock serialises them; the later ones see
  the content hash and are refused.
* identical content under DIFFERENT names: different datasets, so different locks;
  only the file_hash constraint and the csv_<hash> table name stand in the way. This
  is the real race, and where a loser used to get a generic "database error".
* same name, different content: not a rejection since M5 (decision 2): each is the
  next version. Concurrency must still give each a distinct version.

Mutation check (from #191): drop the file_hash constraint and the different-names
test fails —

    ALTER TABLE csv_uploads.csv_files DROP CONSTRAINT csv_files_file_hash_key;

Restore it afterwards with `ADD CONSTRAINT csv_files_file_hash_key UNIQUE (file_hash)`
(delete any duplicate rows the mutated run left first).
"""

from __future__ import annotations

import hashlib
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg2 import sql

from api.db import Conn
from api.services.dynamic_loader import upload_dynamic
from api.tenancy import uploads_schema

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
            "SELECT file_name, file_hash, table_name FROM {}.csv_files "
            "WHERE file_name = ANY(%s) OR file_hash = ANY(%s)").format(sql.Identifier(uploads_schema())),
            (names, hashes))
        return cur.fetchall()


def _table_rows(table: str) -> int:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(uploads_schema()), sql.Identifier(table)))
        return cur.fetchone()[0]


@pytest.mark.integration
@pytest.mark.usefixtures("live_api", "registry_cleanup")
class RegistryRace(unittest.TestCase):
    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def _assert_one_winner(self, results: list[dict], round_no: int) -> tuple[int, dict]:
        ok = [(i, r) for i, r in enumerate(results) if r["status"] == "ok"]
        self.assertEqual(len(ok), 1, f"round {round_no}: expected exactly one winner, "
                                     f"got {[r['status'] for r in results]}")
        return ok[0]

    def _assert_attributable(self, res: dict, winner_name: str, round_no: int):
        """The loser is told it lost, and to whom: not a bare error and not a 500."""
        self.assertEqual(res["status"], "duplicate_file", f"round {round_no}: {res}")
        self.assertEqual(res["existingFileName"], winner_name, f"round {round_no}: {res}")
        self.assertEqual(res["reason"], "content", f"round {round_no}: {res}")

    def test_identical_file_uploaded_concurrently_registers_once(self):
        for n in range(ROUNDS):
            name = f"race_same_{self.tag}_{n}.csv"
            content = f"a,b\n1,{self.tag}_{n}\n2,{self.tag}_{n}\n"
            digest = hashlib.sha256(content.encode()).hexdigest()
            self.registry_cleanup.append(name)

            results = _race([(name, content)] * RACERS)

            _, winner = self._assert_one_winner(results, n)
            for r in results:
                if r["status"] != "ok":
                    self._assert_attributable(r, name, n)
            self.assertEqual(len(_registry([name], [digest])), 1, f"round {n}: registry rows")
            self.assertEqual(_table_rows(winner["tableName"]), 2, f"round {n}: rows duplicated or lost")

    def test_identical_content_under_different_names_registers_once(self):
        """The case where file_hash, not file_name or the dataset lock, is the guard."""
        for n in range(ROUNDS):
            content = f"a,b\n1,{self.tag}_{n}\n2,{self.tag}_{n}\n"
            digest = hashlib.sha256(content.encode()).hexdigest()
            names = [f"race_hash_{self.tag}_{n}_{i}.csv" for i in range(RACERS)]
            self.registry_cleanup.extend(names)

            results = _race([(nm, content) for nm in names])

            idx, winner = self._assert_one_winner(results, n)
            for i, r in enumerate(results):
                if i != idx:
                    self._assert_attributable(r, names[idx], n)
            rows = _registry(names, [digest])
            self.assertEqual(len(rows), 1, f"round {n}: registry rows {rows}")
            self.assertEqual(rows[0][0], names[idx])
            self.assertEqual(_table_rows(winner["tableName"]), 2, f"round {n}: rows duplicated or lost")

    def test_same_name_different_content_gets_distinct_versions(self):
        """Since M5 a repeated filename is the next version, never a rejection. Concurrent
        uploads must not pick the same version number or lose one."""
        for n in range(ROUNDS):
            name = f"race_name_{self.tag}_{n}.csv"
            uploads = [(name, f"a,b\n{i},{self.tag}_{n}_{i}\n") for i in range(RACERS)]
            self.registry_cleanup.append(name)

            results = _race(uploads)

            self.assertEqual([r["status"] for r in results], ["ok"] * RACERS,
                             f"round {n}: every version must be stored, got {results}")
            self.assertEqual(sorted(r["version"] for r in results), list(range(1, RACERS + 1)),
                             f"round {n}: versions must be distinct and gapless")
            self.assertEqual(len({r["dataset"] for r in results}), 1)
            digests = [hashlib.sha256(c.encode()).hexdigest() for _, c in uploads]
            self.assertEqual(len(_registry([name], digests)), RACERS, f"round {n}: registry rows")
