#!/usr/bin/env python3
"""Aggregate pass/fail/skip stats across all stored eval runs.

Mirrors `bun run eval:summary` in gstack.
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
        print(f"{YELLOW}No eval reports directory found.{NC}")
        return

    runs = sorted(p for p in REPORTS_DIR.iterdir() if p.is_dir())
    if not runs:
        print(f"{YELLOW}No eval runs found — run `python3 evals/runner.py` first.{NC}")
        return

    total_runs = 0
    grand_total = grand_passed = grand_failed = grand_skipped = 0
    scenario_stats: dict[str, dict[str, int]] = {}  # key → {pass, fail, skip, total}

    for run_dir in runs:
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        total_runs += 1
        t = summary.get("totals", {})
        grand_total   += t.get("total",   0)
        grand_passed  += t.get("passed",  0)
        grand_failed  += t.get("failed",  0)
        grand_skipped += t.get("skipped", 0)

        for s in summary.get("scenarios", []):
            key = f"{s['tier']}/{s['name']}"
            if key not in scenario_stats:
                scenario_stats[key] = {"pass": 0, "fail": 0, "skip": 0, "total": 0}
            st = scenario_stats[key]
            st["total"] += 1
            if s.get("skipped"):
                st["skip"] += 1
            elif s.get("passed"):
                st["pass"] += 1
            else:
                st["fail"] += 1

    if total_runs == 0:
        print(f"{YELLOW}No readable eval runs found.{NC}")
        return

    overall_pct = round(100.0 * grand_passed / grand_total, 1) if grand_total else 0.0
    fail_col = RED if grand_failed else GREEN

    print(f"\n{CYAN}Eval summary — {total_runs} run(s){NC}")
    print("=" * 55)
    print(f"  Grand total:  {grand_total}")
    print(f"  Passed:       {GREEN}{grand_passed}{NC}")
    print(f"  Failed:       {fail_col}{grand_failed}{NC}")
    print(f"  Skipped:      {YELLOW}{grand_skipped}{NC}")
    print(f"  Pass rate:    {GREEN if overall_pct >= 90 else YELLOW}{overall_pct}%{NC}")

    print(f"\n  {CYAN}Per-scenario pass rate{NC}")
    print(f"  {'Scenario':<40}  {'Pass%':>6}  {'Runs':>5}  {'Fail':>5}")
    print(f"  {'-'*40}  {'-'*6}  {'-'*5}  {'-'*5}")

    for key in sorted(scenario_stats):
        st = scenario_stats[key]
        pct = round(100.0 * st["pass"] / st["total"], 0) if st["total"] else 0
        col = GREEN if pct >= 90 else (YELLOW if pct >= 50 else RED)
        fail_count = st["fail"]
        print(
            f"  {key:<40}  {col}{pct:>5.0f}%{NC}  {st['total']:>5}  "
            f"{(RED if fail_count else DIM)}{fail_count:>5}{NC}"
        )

    print()


if __name__ == "__main__":
    main()
    sys.exit(0)
