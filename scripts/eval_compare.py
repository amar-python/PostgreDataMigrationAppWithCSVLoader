#!/usr/bin/env python3
"""Compare two eval runs side-by-side (auto-picks the two most recent).

Mirrors `bun run eval:compare` in gstack.

Usage:
    python3 scripts/eval_compare.py                          # auto last 2
    python3 scripts/eval_compare.py <run-id-a> <run-id-b>   # explicit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "evals" / "reports"

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


def _load(run_id: str) -> dict:
    path = REPORTS_DIR / run_id / "summary.json"
    if not path.exists():
        print(f"{RED}Run not found: {run_id}{NC}")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario_map(summary: dict) -> dict[str, dict]:
    return {
        f"{s['tier']}/{s['name']}": s
        for s in summary.get("scenarios", [])
    }


def main() -> None:
    runs = sorted(
        (p for p in REPORTS_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.name,
    ) if REPORTS_DIR.exists() else []

    if len(sys.argv) == 3:
        id_a, id_b = sys.argv[1], sys.argv[2]
    elif len(runs) >= 2:
        id_a, id_b = runs[-2].name, runs[-1].name
    else:
        print(
            f"{YELLOW}Need at least 2 eval runs. "
            f"Pass run IDs as arguments or run evals first.{NC}"
        )
        sys.exit(0)

    a = _load(id_a)
    b = _load(id_b)
    a_map = _scenario_map(a)
    b_map = _scenario_map(b)

    all_keys = sorted(set(a_map) | set(b_map))

    print(f"\n{CYAN}Eval comparison{NC}")
    print(f"  A: {id_a}")
    print(f"  B: {id_b}")
    print("=" * 65)
    print(f"  {'Scenario':<40}  {'A':>6}  {'B':>6}  Delta")
    print(f"  {'-'*40}  {'-'*6}  {'-'*6}  -----")

    regressions = improvements = 0

    for key in all_keys:
        sa = a_map.get(key)
        sb = b_map.get(key)

        def _status(s: dict | None) -> str:
            if s is None:
                return "N/A"
            if s.get("skipped"):
                return "SKIP"
            return "PASS" if s.get("passed") else "FAIL"

        sta = _status(sa)
        stb = _status(sb)

        if sta == stb:
            delta = ""
            col = DIM
        elif sta == "PASS" and stb == "FAIL":
            delta = "⬇ REGRESSION"
            col = RED
            regressions += 1
        elif sta == "FAIL" and stb == "PASS":
            delta = "⬆ FIXED"
            col = GREEN
            improvements += 1
        else:
            delta = "~ changed"
            col = YELLOW

        print(f"  {col}{key:<40}  {sta:>6}  {stb:>6}  {delta}{NC}")

    print()
    ta = a.get("totals", {})
    tb = b.get("totals", {})
    print(
        f"  Totals   A: {ta.get('passed', 0)}P/"
        f"{ta.get('failed', 0)}F/{ta.get('skipped', 0)}S"
    )
    print(
        f"           B: {tb.get('passed', 0)}P/"
        f"{tb.get('failed', 0)}F/{tb.get('skipped', 0)}S"
    )
    print()
    if regressions:
        print(f"  {RED}{regressions} regression(s) detected{NC}")
    if improvements:
        print(f"  {GREEN}{improvements} fix(es) confirmed{NC}")
    if not regressions and not improvements:
        print(f"  {DIM}No changes in pass/fail status.{NC}")
    print()


if __name__ == "__main__":
    main()
