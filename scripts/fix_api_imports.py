#!/usr/bin/env python3
"""Convert ``api/`` to package-relative imports so it can be tested.

Why
---
``api/`` currently uses bare imports (``from config import settings``). These
resolve only when the process working directory is ``api/`` — which is what
``scripts/start-api.ps1`` arranges with ``Set-Location``. The API runs fine.

But pytest collects from the repository root, where those imports fail:

    $ python -c "import api.main"
    ModuleNotFoundError: No module named 'config'

So ``tests/test_api.py`` cannot be collected and the API is an untested
surface — invisible even to ``scripts/test_report.py``, which can only account
for tests it can collect.

What this does
--------------
1. Creates ``api/__init__.py`` if missing.
2. Rewrites bare imports of the API's own modules to package-relative form.
   Third-party imports (fastapi, psycopg2, pydantic) are left alone.

Run from the repository root::

    python scripts/fix_api_imports.py --dry-run   # preview
    python scripts/fix_api_imports.py             # apply

Afterwards, update scripts/start-api.ps1 to launch from the root::

    Set-Location $PSScriptRoot\\..
    python -m uvicorn api.main:app --reload --port 8000

Then verify::

    python -c "from api.main import app; print('ok')"
    python -m pytest tests/test_api.py -m unit
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"

# The API's own top-level modules and packages. Anything not in this set (e.g.
# fastapi, psycopg2) is third-party and must not be rewritten.
LOCAL = ("config", "db", "routers", "services")

PATTERNS = [
    # from config import settings      -> from api.config import settings
    # from services.csv_parse import x -> from api.services.csv_parse import x
    (re.compile(rf"^(\s*)from\s+({'|'.join(LOCAL)})(\.[\w.]+)?\s+import\s",
                re.MULTILINE),
     lambda m: f"{m.group(1)}from api.{m.group(2)}{m.group(3) or ''} import "),
    # import db                        -> from api import db
    (re.compile(rf"^(\s*)import\s+({'|'.join(LOCAL)})\s*$", re.MULTILINE),
     lambda m: f"{m.group(1)}from api import {m.group(2)}"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change without writing")
    args = ap.parse_args()

    if not API.is_dir():
        print(f"error: {API} not found — run this from the repository root")
        return 2

    init = API / "__init__.py"
    if init.exists():
        print("  api/__init__.py already present")
    elif args.dry_run:
        print("  would create api/__init__.py")
    else:
        init.write_text('"""FastAPI backend for the CSV Table Hub frontend."""\n',
                        encoding="utf-8")
        print("  created api/__init__.py")

    changed = 0
    for path in sorted(API.rglob("*.py")):
        if path.name == "__init__.py" and path.parent == API:
            continue
        original = path.read_text(encoding="utf-8")
        updated = original
        for pattern, repl in PATTERNS:
            updated = pattern.sub(repl, updated)
        if updated == original:
            continue
        changed += 1
        rel = path.relative_to(ROOT)
        if args.dry_run:
            print(f"  would rewrite {rel}")
            for before, after in zip(original.splitlines(), updated.splitlines()):
                if before != after:
                    print(f"      - {before}\n      + {after}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"  rewrote {rel}")

    print(f"\n{changed} file(s) {'would be ' if args.dry_run else ''}changed")
    if not args.dry_run and changed:
        print("\nNow verify:")
        print('  python -c "from api.main import app; print(\'ok\')"')
        print("  python -m pytest tests/test_api.py -m unit")
        print("\nAnd update scripts/start-api.ps1 to run from the repo root:")
        print("  Set-Location $PSScriptRoot\\..")
        print("  python -m uvicorn api.main:app --reload --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
