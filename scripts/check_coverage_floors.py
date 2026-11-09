#!/usr/bin/env python3
"""Check per-file coverage floors for api/services loaders (#194).

Usage:
    python3 scripts/check_coverage_floors.py coverage-services.json

Reads the JSON coverage report produced by pytest-cov and verifies that
each loader file meets its minimum coverage percentage.  Exits non-zero
if any file drops below its floor.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FLOORS: dict[str, int] = {
    "api/services/csv_parse.py": 79,
    "api/services/dynamic_loader.py": 84,
    "api/services/te_loader.py": 96,
}

GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <coverage-json>", file=sys.stderr)
        return 2

    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"{RED}Coverage report not found: {report_path}{NC}", file=sys.stderr)
        return 1

    with open(report_path) as f:
        data = json.load(f)

    files = data.get("files", {})
    failed = False

    print("\n  api/services coverage floors (#194)")
    print("  " + "─" * 56)
    print(f"  {'File':<40} {'Actual':>7} {'Floor':>7}  Result")
    print("  " + "─" * 56)

    for filepath, floor in sorted(FLOORS.items()):
        info = files.get(filepath)
        if info is None:
            print(f"  {filepath:<40} {'n/a':>7} {floor:>6}%  {RED}MISSING{NC}")
            failed = True
            continue

        pct = info["summary"]["percent_covered"]
        ok = pct >= floor
        tag = f"{GREEN}PASS{NC}" if ok else f"{RED}FAIL{NC}"
        print(f"  {filepath:<40} {pct:>6.1f}% {floor:>6}%  {tag}")
        if not ok:
            failed = True

    print("  " + "─" * 56)

    if failed:
        print(f"\n  {RED}Coverage gate FAILED — one or more loaders below floor.{NC}\n")
        return 1
    else:
        print(f"\n  {GREEN}Coverage gate passed.{NC}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
