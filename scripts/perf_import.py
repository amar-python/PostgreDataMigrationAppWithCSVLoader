#!/usr/bin/env python3
"""Time the approval flow at scale and check it against the decision 8 targets (M7, #111).

    python scripts/perf_import.py --rows 100000 [--enforce] [--json]

Targets (decision 8, on a 2 vCPU / 4 GB instance): a 100,000-row import in under 60 s, and the first
preview page in under 2 s. This runs in-process against the PostgreSQL the API's PG* variables name,
in a throwaway tenant that is dropped afterwards, and prints the hardware it ran on: a pass here proves
the targets only on a machine no faster than the reference instance.

Timed steps: preview (the first preview page, parsing the whole file), stage (store the original and
rows), review page (the first page of stored rows), approve (validates every row), import (COPY and
promote). "Import" below is stage + approve + import, the whole wait from upload to imported rows.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from psycopg2 import sql  # noqa: E402

from api.config import settings  # noqa: E402
from api.db import Conn  # noqa: E402
from api.main import app  # noqa: E402
from api.ratelimit import limiter  # noqa: E402
from api.services import accounts  # noqa: E402
from api.tenancy import migrate_tenant, schema_for  # noqa: E402

MAX_IMPORT_SECONDS = 60.0
MAX_FIRST_PAGE_SECONDS = 2.0
TYPES = ["int8", "text", "text", "numeric", "date", "boolean", "text", "int8"]


def make_csv(rows: int) -> str:
    """A realistic file: eight typed columns, unique rows, no row that fails validation."""
    lines = ["id,name,email,amount,created,active,notes,score"]
    for i in range(1, rows + 1):
        lines.append(f"{i},Person {i},person{i}@example.org,{i % 1000}.{i % 100:02d},2026-{i % 12 + 1:02d}-{i % 28 + 1:02d},"
                     f"{'true' if i % 2 else 'false'},note for row {i} with some text,{i % 97}")
    return "\n".join(lines) + "\n"


def hardware() -> dict:
    mem_gb = None
    try:
        mem_gb = round(int(next(line for line in Path("/proc/meminfo").read_text().splitlines()
                                if line.startswith("MemTotal")).split()[1]) / 1024 / 1024, 1)
    except (OSError, StopIteration):
        pass
    # CPUs this process may use (taskset or a container limit lowers it), not the machine's total.
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    return {"cpus": cpus, "memoryGB": mem_gb, "python": platform.python_version(),
            "os": platform.platform()}


def run(rows: int) -> dict:
    """Run the flow for ``rows`` rows. Returns timings in seconds and the import's reconciliation."""
    settings.RATE_LIMIT_READS_PER_MINUTE = settings.RATE_LIMIT_WRITES_PER_MINUTE = 0
    limiter.reset()
    slug, password = f"perf_{os.getpid()}_{uuid.uuid4().hex[:6]}", "correct horse battery staple"
    content = make_csv(rows)
    timings: dict[str, float] = {}
    with TestClient(app) as client:
        with Conn() as conn, conn.cursor() as cur:
            tenant_id = accounts.create_tenant(cur, slug, "Performance run")
            accounts.add_membership(cur, accounts.create_user(cur, f"{slug}_u", password), tenant_id, "tenant_admin")
            accounts.set_self_approval(cur, slug, True)   # one person does every step
            conn.commit()
        try:
            migrate_tenant(slug)
            login = client.post("/api/auth/login", json={"tenant": slug, "username": f"{slug}_u", "password": password})
            headers = {"Authorization": f"Bearer {login.json()['token']}"}

            def step(name, call):
                started = time.perf_counter()
                res = call()
                timings[name] = round(time.perf_counter() - started, 3)
                assert res.status_code == 200, f"{name}: {res.status_code} {res.text[:300]}"
                return res.json()

            body = {"fileName": "perf.csv", "content": content}
            step("preview", lambda: client.post("/api/csv/preview", headers=headers, json=body))
            staged = step("stage", lambda: client.post("/api/csv/uploads", headers=headers, json={**body, "types": TYPES}))
            upload = staged["uploadId"]
            step("reviewPage", lambda: client.get(f"/api/csv/uploads/{upload}/rows", headers=headers, params={"limit": 100}))
            step("submit", lambda: client.post(f"/api/csv/uploads/{upload}/submit", headers=headers))
            step("approve", lambda: client.post(f"/api/csv/uploads/{upload}/approval", headers=headers,
                                                json={"decision": "approve"}))
            import_headers = {**headers, "Idempotency-Key": "perf"}
            result = step("import", lambda: client.post(f"/api/csv/uploads/{upload}/import", headers=import_headers))
        finally:
            with Conn() as conn, conn.cursor() as cur:   # uploads are insert-only; dropping the tenant clears them
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
                control = sql.Identifier(settings.CONTROL_SCHEMA)
                cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(control), (slug,))
                cur.execute(sql.SQL("DELETE FROM {}.users WHERE username = %s").format(control), (f"{slug}_u",))
                conn.commit()
    timings["upToImported"] = round(sum(timings[k] for k in ("stage", "submit", "approve", "import")), 3)
    # ru_maxrss is KiB on Linux. This process only (the API and the CSV in memory), not PostgreSQL's.
    return {"rows": rows, "timings": timings, "reconciliation": result["reconciliation"],
            "csvMB": round(len(content.encode()) / 1024 / 1024, 1), "hardware": hardware(),
            "peakPythonMB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}


def verdict(report: dict, max_import: float = MAX_IMPORT_SECONDS, max_page: float = MAX_FIRST_PAGE_SECONDS) -> dict:
    t = report["timings"]
    return {"importUnderTarget": t["upToImported"] <= max_import,
            "firstPageUnderTarget": max(t["preview"], t["reviewPage"]) <= max_page}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--enforce", action="store_true", help="exit 1 if a target is missed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = run(args.rows)
    report["targets"] = {"maxImportSeconds": MAX_IMPORT_SECONDS, "maxFirstPageSeconds": MAX_FIRST_PAGE_SECONDS,
                         **verdict(report)}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        t, hw = report["timings"], report["hardware"]
        print(f"{report['rows']:,} rows ({report['csvMB']} MB) on {hw['cpus']} CPUs, {hw['memoryGB']} GB: {hw['os']}")
        for name in ("preview", "stage", "reviewPage", "submit", "approve", "import", "upToImported"):
            print(f"  {name:<13}{t[name]:>8.2f} s")
        print(f"  peak memory of this process: {report['peakPythonMB']} MB (PostgreSQL's is separate)")
        print(f"  reconciliation {report['reconciliation']}")
        ok = report["targets"]
        print(f"  import (stage to imported) <= {MAX_IMPORT_SECONDS:.0f} s: {'yes' if ok['importUnderTarget'] else 'NO'}; "
              f"first preview page <= {MAX_FIRST_PAGE_SECONDS:.0f} s: {'yes' if ok['firstPageUnderTarget'] else 'NO'}")
        print("  (targets are for a 2 vCPU / 4 GB instance; this machine is above)" if (hw["cpus"] or 0) > 2 else "")
    return 1 if args.enforce and not all(report["targets"][k] for k in ("importUnderTarget", "firstPageUnderTarget")) else 0


if __name__ == "__main__":
    sys.exit(main())
