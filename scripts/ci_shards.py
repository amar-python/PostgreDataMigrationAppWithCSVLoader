#!/usr/bin/env python3
"""Split the test files into shards that CI runs in parallel.

The integration job used to run the whole suite in one go, then the system tests again, then everything a third time
for coverage: 25 to 40 minutes in a row. The suite is now split by test file into SHARDS parts; each part runs in its
own job with its own PostgreSQL (the system tests share databases and assume a fresh one, so they cannot share a
server). Each shard still runs through ``scripts/test_report.py --strict``, so every test it holds is accounted for.

    python3 scripts/ci_shards.py files --shard 2 --of 3     # the files shard 2 of 3 runs, one per line
    python3 scripts/ci_shards.py plan --of 3                 # the whole split and its estimated times
    python3 scripts/ci_shards.py update-weights junit.xml    # record fresh durations from a full run's JUnit report

How the split is made: files are sorted by their recorded duration (``ci/shard_weights.json``, seconds) and handed out
heaviest first to whichever shard is lightest so far. A file with no recorded duration counts DEFAULT_WEIGHT, so a new
test file always lands in a shard. ``tests/accessibility`` is left out: it has its own job.

Regenerate the durations when the suite changes a lot (a full local run with ``--junitxml``, then ``update-weights``).
A stale split only makes the shards less even; it can never drop a file, because ``tests/unit/test_ci_shards.py``
checks that every file pytest collects is in exactly one shard.

Exit status: 0 on success; 2 for a shard that does not exist (a typo in the workflow must fail the job, not run
nothing and pass).
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_PATH = ROOT / "ci" / "shard_weights.json"
SHARDS = 3                      # keep in step with the `shard:` matrix in .github/workflows/quality-gate.yml (tested)
DEFAULT_WEIGHT = 20.0           # seconds, for a file with no recorded duration
EXCLUDED_PREFIXES = ("tests/accessibility/",)


def test_files(root: Path = ROOT) -> list[str]:
    """Every test file CI runs in a shard, as sorted repo-relative posix paths."""
    found: set[str] = set()
    for pattern in ("test_*.py", "*_test.py"):
        for path in (root / "tests").rglob(pattern):
            rel = path.relative_to(root).as_posix()
            if "__pycache__" in rel or rel.startswith(EXCLUDED_PREFIXES):
                continue
            found.add(rel)
    return sorted(found)


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except FileNotFoundError:
        return {}


def assign(files: list[str], weights: dict[str, float], n: int) -> list[list[str]]:
    """Heaviest first into the lightest shard; deterministic; each shard's files sorted."""
    shards: list[list[str]] = [[] for _ in range(n)]
    totals = [0.0] * n
    for rel in sorted(files, key=lambda f: (-weights.get(f, DEFAULT_WEIGHT), f)):
        lightest = min(range(n), key=lambda k: (totals[k], k))
        shards[lightest].append(rel)
        totals[lightest] += weights.get(rel, DEFAULT_WEIGHT)
    return [sorted(shard) for shard in shards]


def weights_from_junit(xml_path: Path, root: Path = ROOT) -> dict[str, float]:
    """Seconds per test file from a JUnit report: a test's classname starts with its module path."""
    totals: dict[str, float] = {}
    # nosec B314 # a JUnit file pytest wrote in the operator's own full run (the same case as scripts/test_report.py)
    for case in ET.parse(xml_path).getroot().iter("testcase"):  # nosec B314
        parts = (case.get("classname") or "").split(".")
        for k in range(len(parts), 0, -1):
            rel = "/".join(parts[:k]) + ".py"
            if (root / rel).is_file():
                totals[rel] = totals.get(rel, 0.0) + float(case.get("time") or 0)
                break
    return {rel: round(seconds, 2) for rel, seconds in sorted(totals.items())}


def _plan(n: int) -> int:
    weights = load_weights()
    for k, shard in enumerate(assign(test_files(), weights, n), start=1):
        seconds = sum(weights.get(f, DEFAULT_WEIGHT) for f in shard)
        print(f"shard {k}: {len(shard)} files, about {seconds / 60:.1f} min")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    files = sub.add_parser("files", help="print one shard's files, one per line")
    files.add_argument("--shard", type=int, required=True)
    files.add_argument("--of", type=int, default=SHARDS, dest="of")
    plan = sub.add_parser("plan", help="print every shard with an estimate")
    plan.add_argument("--of", type=int, default=SHARDS, dest="of")
    update = sub.add_parser("update-weights", help="regenerate durations from a JUnit report of a full run")
    update.add_argument("junit")
    update.add_argument("--output", default=str(WEIGHTS_PATH))
    args = parser.parse_args(argv)

    if args.command == "update-weights":
        weights = weights_from_junit(Path(args.junit))
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(weights, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {len(weights)} durations in {out}")
        return 0
    if args.of < 1:
        print(f"--of must be at least 1, got {args.of}", file=sys.stderr)
        return 2
    if args.command == "plan":
        return _plan(args.of)
    if not 1 <= args.shard <= args.of:
        print(f"shard {args.shard} does not exist: shards are 1 to {args.of}", file=sys.stderr)
        return 2
    print("\n".join(assign(test_files(), load_weights(), args.of)[args.shard - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
