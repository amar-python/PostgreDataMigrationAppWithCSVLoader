#!/usr/bin/env python3
"""Decide whether a change needs the slow database jobs, for the `changes` job of .github/workflows/quality-gate.yml.

    python3 scripts/ci_changes.py --event pull_request --base <sha> --head <sha>     # prints  code=true  or  code=false

``code=false`` lets the three database jobs (shards, egress, coverage) be skipped: a change that touches nothing but
documentation cannot alter what they test. The fast jobs (free tier, browser, accessibility) always run, and the free
tier includes the tests that check the documents against the code.

Documentation means a file under ``docs/`` or ``DECISIONS/``, or a markdown file in the repository root. It counts as
CODE, so everything runs, when any test, eval, script, source file or workflow names it by file name: a test that reads
``docs/ROLES.md`` can break when that file changes, and only the database jobs run some of those tests. That rule keeps
itself current: nobody has to maintain a list of "documents tests read".

When in doubt it runs everything: a push (to main), any event other than a pull request, a diff that cannot be read, an
empty diff. Skipping is only ever the answer to "every changed file is a document that nothing reads".
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PREFIXES = ("docs/", "DECISIONS/")
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build/csv/logs",
}
MAX_BYTES = 2_000_000


def is_doc(path: str) -> bool:
    return path.startswith(DOC_PREFIXES) or ("/" not in path and path.lower().endswith(".md"))


def _scan(root: Path):
    """The text of every non-document file under root (documents mention each other constantly, so they are not read)."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and f"{rel_dir}/{d}".lstrip("./") not in SKIP_DIRS]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            if is_doc(rel):
                continue
            path = Path(dirpath) / name
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                yield path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue


def is_docs_only(paths: list[str], root: Path = ROOT) -> bool:
    """True only if every path is a document that no other file names. Empty input is not evidence: False."""
    if not paths or not all(is_doc(p) for p in paths):
        return False
    names = {Path(p).name for p in paths}
    for text in _scan(root):
        if any(name in text for name in names):
            return False
    return True


def decide(event: str, paths: list[str] | None, root: Path = ROOT) -> str:
    """'true' (run the database jobs) or 'false' (skip them)."""
    if event != "pull_request" or not paths:
        return "true"
    return "false" if is_docs_only(paths, root) else "true"


def changed_files(base: str, head: str, root: Path = ROOT) -> list[str] | None:
    """Paths changed between base and head (the merge-base form GitHub shows), or None if git cannot say."""
    done = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], cwd=root, capture_output=True, text=True)
    if done.returncode != 0:
        print(f"git diff failed: {done.stderr.strip()}", file=sys.stderr)
        return None
    return [line for line in done.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    args = parser.parse_args(argv)
    paths = changed_files(args.base, args.head) if args.event == "pull_request" and args.base and args.head else None
    answer = decide(args.event, paths)
    why = (
        "not a pull request"
        if args.event != "pull_request"
        else ("no readable diff, so everything runs" if not paths else f"{len(paths)} changed file(s)")
    )
    print(f"{why} -> database jobs {'run' if answer == 'true' else 'skipped (documentation only)'}", file=sys.stderr)
    line = f"code={answer}"
    print(line)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
