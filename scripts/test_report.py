#!/usr/bin/env python3
"""Run the test suite and print a final result that accounts for every test.

Why this exists
---------------
A run that reports "OK" tells you nothing about what it did *not* do. Silent
skips and out-of-scope tests are how a suite ends up looking green while
covering less than you think.

This reporter guarantees the final block always states:

  * PASSED   — executed and passed
  * FAILED   — executed and failed (assertion)
  * ERROR    — executed and errored (including unmet prerequisites, which this
               project treats as failures, never skips)
  * SKIPPED  — every skip, with its reason. Should always be 0; the section is
               printed even when empty so its absence is never ambiguous.
  * NOT RUN  — collected but deselected by the marker filter, with the filter
               that excluded them. These are not skips; they are out of this
               invocation's scope and must run elsewhere (see --markers).

Usage
-----
    python3 scripts/test_report.py                 # whole suite
    python3 scripts/test_report.py --markers "unit or security"
    python3 scripts/test_report.py --strict        # exit 1 if anything skipped

Exit codes: 0 all executed tests passed; 1 otherwise (or any skip under
--strict).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


def _collect_all_ids() -> set[str]:
    """Every test pytest can see, ignoring marker filters."""
    r = subprocess.run(
        # -o addopts="" neutralises pytest.ini's -q, which would otherwise collapse
        # the listing to per-file counts instead of individual test ids.
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header",
         "-o", "addopts="],
        cwd=ROOT, capture_output=True, text=True,
    )
    ids = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if "::" in line and not line.startswith(("=", "-", "[")):
            ids.add(line)
    return ids


def _run(markers: str | None, xml_path: Path) -> int:
    """Run pytest and return its exit code.

    Exit code 2 means the run was INTERRUPTED (typically a collection error),
    which is materially different from tests being deselected — nothing ran at
    all. The final block distinguishes the two so a broken import is not
    reported as a marker filter.
    """
    cmd = [sys.executable, "-m", "pytest", f"--junitxml={xml_path}", "-q", "--no-header"]
    if markers:
        cmd += ["-m", markers]
    return subprocess.run(cmd, cwd=ROOT).returncode


def _parse(xml_path: Path):
    """Return (passed, failed, errored, skipped) from the JUnit XML."""
    passed, failed, errored, skipped = [], [], [], []
    if not xml_path.exists():
        return passed, failed, errored, skipped
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        tid = f"{cls}::{name}" if cls else name
        if (n := case.find("skipped")) is not None:
            skipped.append((tid, (n.get("message") or "").strip() or "no reason given"))
        elif (n := case.find("failure")) is not None:
            failed.append((tid, (n.get("message") or "").strip().splitlines()[0]
                           if n.get("message") else ""))
        elif (n := case.find("error")) is not None:
            errored.append((tid, (n.get("message") or "").strip().splitlines()[0]
                            if n.get("message") else ""))
        else:
            passed.append(tid)
    return passed, failed, errored, skipped


def _norm(tid: str) -> str:
    """JUnit uses dotted classnames; collection uses file paths. Compare on the leaf."""
    return tid.split("::")[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markers", default=None,
                    help='pytest -m expression, e.g. "unit or security"')
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any test was skipped")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        xml_path = Path(td) / "results.xml"
        all_ids = _collect_all_ids()
        exit_code = _run(args.markers, xml_path)
        passed, failed, errored, skipped = _parse(xml_path)

    # pytest's own exit code 2 == interrupted, e.g. a collection error.
    interrupted = exit_code == 2

    executed = {_norm(t) for t in passed} \
        | {_norm(t) for t, _ in failed} \
        | {_norm(t) for t, _ in errored} \
        | {_norm(t) for t, _ in skipped}
    not_run = sorted(i for i in all_ids if _norm(i) not in executed)

    total = len(passed) + len(failed) + len(errored) + len(skipped)
    bar = "=" * 66
    print(f"\n{CYAN}{bar}\n  FINAL RESULT — every test accounted for\n{bar}{NC}")
    if args.markers:
        print(f"  marker filter : -m \"{args.markers}\"")
    print(f"  collected     : {len(all_ids)}")
    print(f"  executed      : {total}")
    print(f"  {GREEN}PASSED{NC}        : {len(passed)}")
    print(f"  {RED}FAILED{NC}        : {len(failed)}")
    print(f"  {RED}ERROR{NC}         : {len(errored)}")
    print(f"  {YELLOW}SKIPPED{NC}       : {len(skipped)}")
    not_run_reason = ("run INTERRUPTED before they could execute"
                      if interrupted else "deselected by the marker filter")
    print(f"  {DIM}NOT RUN{NC}       : {len(not_run)}  {DIM}({not_run_reason}){NC}")

    for label, colour, items in (("FAILED", RED, failed), ("ERROR", RED, errored)):
        if items:
            print(f"\n{colour}  {label}{NC}")
            for tid, msg in items:
                print(f"    - {tid}")
                if msg:
                    print(f"      {DIM}{msg[:110]}{NC}")

    # Always printed, even when empty — an absent section would be ambiguous.
    print(f"\n{YELLOW}  SKIPPED ({len(skipped)}){NC}")
    if skipped:
        for tid, reason in skipped:
            print(f"    - {tid}\n      {DIM}reason: {reason[:110]}{NC}")
        print(f"    {YELLOW}Policy: unmet prerequisites must FAIL, not skip.{NC}")
    else:
        print(f"    {GREEN}none — no test was skipped{NC}")

    print(f"\n{DIM}  NOT RUN ({len(not_run)}){NC}")
    if not_run:
        for tid in not_run:
            print(f"    {DIM}- {tid}{NC}")
        if interrupted:
            print(f"    {RED}The run was interrupted (exit code 2) — most often a"
                  f" collection error above. These tests never executed.{NC}")
        else:
            print(f"    {DIM}Deselected by the marker filter, not skipped. They must"
                  f" run in another job.{NC}")
    else:
        print(f"    {GREEN}none — every collected test was executed{NC}")

    ok = (not failed and not errored and not interrupted
          and not (args.strict and skipped))
    print(f"\n{bar}")
    print(f"  {(GREEN + 'RESULT: PASS') if ok else (RED + 'RESULT: FAIL')}{NC}")
    print(f"{bar}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
