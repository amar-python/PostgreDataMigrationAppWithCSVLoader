#!/usr/bin/env python3
"""Check coverage floors: per-file for the api/services loaders (#194), and per package for the API and the
Streamlit app (#274, #278).

Usage:
    python3 scripts/check_coverage_floors.py coverage.json

Reads the JSON coverage report produced by pytest-cov (`--cov=api --cov=streamlit_app`) and verifies that each
loader file, and each package as a whole, meets its minimum coverage percentage. A package's figure is covered
statements over all statements in it (not an average of file percentages). A file or package missing from the
report fails, so dropping a `--cov=` option cannot quietly stop it being measured. Exits non-zero if anything
drops below its floor.

The floors sit a few points under what the full suite measured on 19 Nov 2026 (api 94.4 %, streamlit_app 97.5 %),
so new code has some room and a real loss of coverage does not. Raise them when the numbers rise.
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

# Whole-package floors, as covered statements over all statements under the prefix.
PACKAGE_FLOORS: dict[str, int] = {
    "api/": 90,
    "streamlit_app/": 92,
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

    print("\n  api/services loader floors (#194)")
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

    print("\n  package coverage floors (#274, #278)")
    print("  " + "─" * 56)
    print(f"  {'Package':<40} {'Actual':>7} {'Floor':>7}  Result")
    print("  " + "─" * 56)
    for prefix, floor in sorted(PACKAGE_FLOORS.items()):
        members = [v["summary"] for name, v in files.items() if name.startswith(prefix)]
        statements = sum(m.get("num_statements", 0) for m in members)
        if not members or statements == 0:
            print(f"  {prefix:<40} {'n/a':>7} {floor:>6}%  {RED}MISSING{NC}")
            failed = True
            continue
        pct = 100.0 * sum(m.get("covered_lines", 0) for m in members) / statements
        ok = pct >= floor
        tag = f"{GREEN}PASS{NC}" if ok else f"{RED}FAIL{NC}"
        print(f"  {prefix:<40} {pct:>6.1f}% {floor:>6}%  {tag}")
        if not ok:
            failed = True
    print("  " + "─" * 56)

    if failed:
        print(f"\n  {RED}Coverage gate FAILED — a loader or a package is below its floor or missing.{NC}\n")
        return 1
    else:
        print(f"\n  {GREEN}Coverage gate passed.{NC}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
