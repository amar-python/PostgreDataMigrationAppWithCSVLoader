#!/usr/bin/env python3
"""Diff-based test selector — shows which pytest tests to run given the current git diff.

Mirrors `bun run eval:select` in gstack.

Usage:
    python3 scripts/select_tests.py          # compare vs origin/main
    python3 scripts/select_tests.py HEAD~1   # compare vs previous commit
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
DIM    = "\033[2m"
NC     = "\033[0m"

# Map of changed path patterns → pytest marks / files to run
_RULES: list[tuple[str, str, str]] = [
    # (path_fragment, mark_expression, human_label)
    ("build/csv/validator",      "unit or snapshot or regression",  "validator changed → unit + snapshot + regression"),
    ("evals/runner",             "unit",                             "runner changed → unit"),
    ("evals/gap_report",         "unit",                             "gap_report changed → unit"),
    ("evals/datasets/",          "unit",                             "eval dataset changed → unit (tier_p)"),
    ("evals/expected/",          "unit",                             "expected file changed → unit (tier_p)"),
    ("build/environments/",      "integration or e2e or parity",    "env SQL changed → integration + parity"),
    ("build/schema/",            "integration or e2e or parity",    "schema changed → integration + parity"),
    ("tests/suites/",            "integration",                      "SQL test suite changed → integration"),
    ("tests/test_",              "unit",                             "test file changed → unit"),
    ("scripts/",                 "security",                         "scripts changed → security scan"),
    ("build/adapters/",          "security",                         "adapter changed → security scan"),
    ("build/csv/loader_",        "e2e",                              "loader changed → e2e"),
]

_DEFAULT_MARKS = "unit"  # always run at minimum when diff is unclear


def _git_diff(base: str) -> list[str]:
    for cmd in [
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", "HEAD~1"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()
        except FileNotFoundError:
            pass
    return []


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    changed = _git_diff(base)

    print(f"\n{CYAN}Test selector — diff vs {base}{NC}")
    print("=" * 55)

    if not changed:
        print(f"  {YELLOW}No changed files detected — running default tier: {_DEFAULT_MARKS}{NC}")
        print(f"\n  pytest -m \"{_DEFAULT_MARKS}\" tests/\n")
        return

    print(f"  {DIM}Changed files:{NC}")
    for f in changed:
        print(f"    {DIM}{f}{NC}")
    print()

    matched_marks: set[str] = set()
    matched_labels: list[str] = []

    for path in changed:
        for fragment, marks, label in _RULES:
            if fragment in path:
                for m in marks.split(" or "):
                    matched_marks.add(m.strip())
                if label not in matched_labels:
                    matched_labels.append(label)
                break

    if not matched_marks:
        matched_marks.add(_DEFAULT_MARKS)
        matched_labels.append("no specific rule matched → running unit tests")

    mark_expr = " or ".join(sorted(matched_marks))

    print(f"  {GREEN}Matched rules:{NC}")
    for label in matched_labels:
        print(f"    • {label}")

    print(f"\n  {GREEN}Recommended command:{NC}")
    print(f"    pytest -m \"{mark_expr}\" tests/\n")


if __name__ == "__main__":
    main()
