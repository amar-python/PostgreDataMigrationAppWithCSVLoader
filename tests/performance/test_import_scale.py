"""The approval flow at scale against the decision 8 targets (M7, #111). Needs a live PostgreSQL.

Runs scripts/perf_import.py's flow with PERF_ROWS rows (default 10,000, a quick smoke). The targets
(100,000 rows imported in under 60 s; first preview page under 2 s) are only asserted when
PERF_ENFORCE=1, because a time on a developer laptop or a CI runner says nothing about the 2 vCPU /
4 GB reference instance. To measure properly: PERF_ROWS=100000 PERF_ENFORCE=1 on that instance, or
`python scripts/perf_import.py --rows 100000 --enforce`.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "perf_import.py"


def _harness():
    spec = importlib.util.spec_from_file_location("perf_import", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportAtScale(unittest.TestCase):
    def test_every_row_is_imported_and_the_targets_hold_when_enforced(self):
        harness = _harness()
        rows = int(os.environ.get("PERF_ROWS", "10000"))
        report = harness.run(rows)
        self.assertEqual(report["reconciliation"],
                         {"rowsIn": rows, "excluded": 0, "edited": 0, "duplicate": 0, "imported": rows})
        self.assertEqual(set(report["timings"]),
                         {"preview", "stage", "reviewPage", "submit", "approve", "import", "upToImported"})
        if os.environ.get("PERF_ENFORCE") == "1":
            verdict = harness.verdict(report)
            self.assertTrue(verdict["importUnderTarget"], report["timings"])
            self.assertTrue(verdict["firstPageUnderTarget"], report["timings"])

    def test_the_synthetic_file_has_the_shape_the_targets_assume(self):
        harness = _harness()
        lines = harness.make_csv(100).splitlines()
        self.assertEqual((len(lines), len(lines[0].split(","))), (101, 8))
        self.assertEqual(len(set(lines)), 101, "rows are unique, so nothing is skipped as a duplicate")
