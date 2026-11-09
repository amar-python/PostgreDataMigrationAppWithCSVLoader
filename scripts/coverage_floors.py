#!/usr/bin/env python3
"""Fail the gate when a loader's coverage drops below its floor (#194).

pytest-cov only has a single project-wide ``--cov-fail-under``, which would let
te_loader.py (96%) hide a collapse in csv_parse.py (79%). This enforces one floor
per file instead.

    pytest ... --cov=api/services --cov-report=json:coverage.json
    python scripts/coverage_floors.py [coverage.json]

Floors are the figures measured against a deployed PostgreSQL (365 passed),
rounded down — see #194. They are a ratchet: raise one when its file's coverage
rises, never lower one to get a build through. A floored file that does not
appear in the report FAILS: a rename or a missing --cov must not pass silently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# percent, per file. Product owner to confirm the values (#194).
FLOORS = {
    "api/services/csv_parse.py": 79,
    "api/services/dynamic_loader.py": 84,
    "api/services/te_loader.py": 96,
}


def check(report: dict, floors: dict[str, float] = FLOORS) -> list[str]:
    """Return one failure message per file below its floor or missing from the report."""
    files = {k.replace("\\", "/"): v for k, v in report.get("files", {}).items()}
    failures = []
    for name, floor in floors.items():
        entry = files.get(name)
        if entry is None:
            failures.append(f"{name}: not in the coverage report (was --cov=api/services passed?)")
            continue
        got = entry["summary"]["percent_covered"]
        if got < floor:
            failures.append(f"{name}: {got:.1f}% is below its floor of {floor}%")
    return failures


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "coverage.json"
    if not path.exists():
        print(f"{path} not found — run pytest with --cov-report=json:{path.name} first.", file=sys.stderr)
        return 1
    report = json.loads(path.read_text())
    files = {k.replace("\\", "/"): v for k, v in report.get("files", {}).items()}

    print("\napi/services coverage floors")
    print(f"  {'file':<34}{'covered':>9}{'floor':>8}")
    for name, floor in FLOORS.items():
        e = files.get(name)
        got = f"{e['summary']['percent_covered']:.1f}%" if e else "missing"
        print(f"  {name:<34}{got:>9}{str(floor) + '%':>8}")

    failures = check(report)
    for f in failures:
        print(f"::error::coverage floor: {f}")
    print("\nRESULT: " + ("FAIL" if failures else "PASS"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
