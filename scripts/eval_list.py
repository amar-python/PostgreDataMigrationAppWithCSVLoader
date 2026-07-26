#!/usr/bin/env python3
"""List all past eval runs stored in evals/reports/.

Mirrors `bun run eval:list` in gstack.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT        = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "evals" / "reports"

GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
DIM    = "\033[2m"
NC     = "\033[0m"


def main() -> None:
    if not REPORTS_DIR.exists():
        print(f"{YELLOW}No eval reports found — run `python3 evals/runner.py` first.{NC}")
        return

    runs = sorted(
        (p for p in REPORTS_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )

    if not runs:
        print(f"{YELLOW}No eval runs found in {REPORTS_DIR.relative_to(ROOT)}{NC}")
        return

    print(f"\n{CYAN}Eval runs ({len(runs)} total) — most recent first{NC}")
    print("=" * 70)
    print(f"  {'Run ID':<30}  {'Total':>5}  {'Pass':>5}  {'Fail':>5}  {'Skip':>5}")
    print(f"  {'-'*30}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}")

    for run_dir in runs:
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            print(f"  {DIM}{run_dir.name:<30}  (no summary.json){NC}")
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            t = summary.get("totals", {})
            total   = t.get("total",   0)
            passed  = t.get("passed",  0)
            failed  = t.get("failed",  0)
            skipped = t.get("skipped", 0)
            fail_col = RED if failed else NC
            print(
                f"  {run_dir.name:<30}  {total:>5}  "
                f"{GREEN}{passed:>5}{NC}  {fail_col}{failed:>5}{NC}  "
                f"{YELLOW}{skipped:>5}{NC}"
            )
        except (json.JSONDecodeError, KeyError):
            print(f"  {run_dir.name:<30}  {RED}(corrupt summary.json){NC}")

    print()


if __name__ == "__main__":
    main()
    sys.exit(0)
