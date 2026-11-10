"""Produce the sample Migration Verification Report (#59) from a real run.

Drives a RUNNING API with the two synthetic CSVs in docs/samples/, then
cross-checks what the API said against the database itself. Every figure in the
report is taken from that run; nothing is typed in by hand. Outputs:

    docs/samples/verification-run-evidence.json            raw API responses + DB reads
    docs/samples/MIGRATION_VERIFICATION_REPORT_SAMPLE.md   the report, rendered from the evidence

Prerequisites (a FRESH database, so counts start at zero): deployed dev schema,
a tenant admin, the API running. From the repo root, with the API's PG* vars set:

    export TE_ADMIN_PASSWORD='<12+ chars>'      # the tenant admin's password
    python scripts/sample_verification_run.py   # --tenant dev --username admin by default

Exits 1 if any check fails, so a regression shows up as a red report, not a quiet one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "docs" / "samples"

# The outcome the T&E fixture is DESIGNED to produce, declared before the run:
# data rows (1-based, header excluded) of orgs_sample.csv that the database must reject.
EXPECTED_REJECTS = {
    6: "duplicate name (unique constraint)",
    7: "org_type 'startup' not in the allowed list (check constraint)",
    8: "country 'AUS' too long for a 2-character code",
    9: "name is empty (not-null constraint)",
}


class Api:
    def __init__(self, base: str):
        self.base, self.token = base.rstrip("/"), None

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        headers = {"content-type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(
            self.base + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def upload(api: Api, name: str, content: str, mode: str, target: str | None = None) -> dict:
    """Preview, then upload with the preview's inferred types: the same two calls the UI makes."""
    _, prev = api.call("POST", "/api/csv/preview", {"fileName": name, "content": content})
    body = {"fileName": name, "content": content, "mode": mode, "types": prev.get("inferredTypes")}
    if target:
        body["targetTable"] = target
    status, resp = api.call("POST", "/api/csv/upload", body)
    resp.pop("logs", None)  # per-step timestamps are noise in a report
    return {"http": status, "preview": {k: prev.get(k) for k in ("status", "inferredTypes", "teTableMatch")}, "response": resp}


def collect(api: Api, conn) -> dict:
    ev: dict = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    cur = conn.cursor()

    ev["health"] = api.call("GET", "/api/health")[1]
    ev["environment"] = {
        "code_commit": git("rev-parse", "HEAD"),
        "tracked_files_modified": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "os": platform.platform(),
    }

    # --- Dataset A: T&E mode, deliberately defective --------------------------------
    orgs_bytes = (SAMPLES / "orgs_sample.csv").read_bytes()
    orgs = orgs_bytes.decode("utf-8")
    src_rows = [ln.split(",") for ln in orgs.splitlines()[1:]]
    a = upload(api, "orgs_sample.csv", orgs, "te", "organisations")
    resp = a["response"]
    schema, table = resp["tableName"].split(".")
    cur.execute(f'SELECT name, org_type, country FROM "{schema}"."{table}" ORDER BY name')
    db_rows = [list(r) for r in cur.fetchall()]
    cur.execute(f'SELECT file_hash, row_count, total_rows, failed_rows FROM "{schema}".csv_files WHERE file_name=%s',
                ("orgs_sample.csv",))
    reg = cur.fetchone()
    expected_loaded = sorted(r for i, r in enumerate(src_rows, 1) if i not in EXPECTED_REJECTS)
    ev["te"] = {
        "file": "orgs_sample.csv", "bytes": len(orgs_bytes), "sha256": hashlib.sha256(orgs_bytes).hexdigest(),
        "source_rows": len(src_rows), "source_lines": {i: ",".join(r) for i, r in enumerate(src_rows, 1)},
        "api": a, "target": resp["tableName"], "db_row_count": len(db_rows), "db_rows": db_rows,
        "registry": {"file_hash": reg[0], "row_count": reg[1], "total_rows": reg[2], "failed_rows": reg[3]},
        "expected_rejects": EXPECTED_REJECTS,
        "rejected_row_numbers": sorted(e["rowNumber"] for e in resp.get("rowErrors", [])),
        "loaded_matches_source": sorted(db_rows) == expected_loaded,
    }

    # --- Dataset B: dynamic mode, clean, then duplicate handling --------------------
    eq_bytes = (SAMPLES / "equipment_register.csv").read_bytes()
    eq = eq_bytes.decode("utf-8")
    b = upload(api, "equipment_register.csv", eq, "dynamic")
    bt = b["response"]["tableName"]
    bs = ev["te"]["target"].split(".")[0]  # dynamic tables live in the same tenant schema
    cur.execute(f'SELECT count(*) FROM "{bs}"."{bt}"')
    b_count = cur.fetchone()[0]
    cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (bs, bt))
    cols = [list(r) for r in cur.fetchall() if not r[0].startswith("_")]
    cur.execute(f'SELECT file_hash FROM "{bs}".csv_files WHERE file_name=%s', ("equipment_register.csv",))
    ev["dynamic"] = {
        "file": "equipment_register.csv", "bytes": len(eq_bytes), "sha256": hashlib.sha256(eq_bytes).hexdigest(),
        "source_rows": len(eq.splitlines()) - 1, "api": b, "table": bt, "db_row_count": b_count,
        "db_columns": cols, "registry_file_hash": cur.fetchone()[0],
        "duplicate_same_name": upload(api, "equipment_register.csv", eq, "dynamic")["response"],
        "duplicate_renamed": upload(api, "equipment_register_copy.csv", eq, "dynamic")["response"],
    }

    # --- Observed deployment posture (read from the running system, not from our env) --
    unauth = urllib.request.Request(api.base + "/api/csv/files")
    try:
        with urllib.request.urlopen(unauth) as r:
            unauth_status = r.status
    except urllib.error.HTTPError as e:
        unauth_status = e.code
    cur.execute("SELECT DISTINCT usename FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND usename IS NOT NULL")
    api_roles = sorted(r[0] for r in cur.fetchall())
    cur.execute("SELECT tableowner FROM pg_tables WHERE schemaname=%s AND tablename='audit_log'", (bs,))
    ev["posture"] = {"unauthenticated_request_status": unauth_status, "database_roles_connected": api_roles,
                     "audit_log_owner": cur.fetchone()[0]}

    # --- Audit trail ----------------------------------------------------------------
    ev["audit"] = {
        "log": api.call("GET", "/api/audit/log?limit=200")[1],
        "verify": api.call("GET", "/api/audit/verify")[1],
    }
    ev["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return ev


def checks(ev: dict) -> list[tuple[str, str, bool]]:
    """(check, observed, passed). Each compares two independent sources."""
    te, dy, au = ev["te"], ev["dynamic"], ev["audit"]
    r = te["api"]["response"]
    entries = au["log"]["entries"]
    return [
        ("T&E: every source row is accounted for (loaded + rejected = source)",
         f"{r['insertedRows']} + {r['failedRows']} + {r['duplicateRowsSkipped']} = {r['insertedRows'] + r['failedRows'] + r['duplicateRowsSkipped']} of {te['source_rows']}",
         r["insertedRows"] + r["failedRows"] + r["duplicateRowsSkipped"] == te["source_rows"]),
        ("T&E: rows in the database equal the rows the API reported loaded",
         f"database {te['db_row_count']}, API {r['insertedRows']}", te["db_row_count"] == r["insertedRows"]),
        ("T&E: the rows rejected are exactly the rows the fixture was designed to produce",
         f"rejected {te['rejected_row_numbers']}, expected {sorted(te['expected_rejects'])}",
         te["rejected_row_numbers"] == sorted(int(k) for k in te["expected_rejects"])),
        ("T&E: every loaded row matches its source row, field for field",
         f"{te['db_row_count']} of {te['db_row_count']} match" if te["loaded_matches_source"] else "mismatch",
         te["loaded_matches_source"]),
        ("T&E: file hash recorded by the system equals an independently computed SHA-256",
         te["registry"]["file_hash"][:16] + "…", te["registry"]["file_hash"] == te["sha256"]),
        ("T&E: registry counts equal the API response",
         f"registry loaded {te['registry']['row_count']} / failed {te['registry']['failed_rows']}",
         te["registry"]["row_count"] == r["insertedRows"] and te["registry"]["failed_rows"] == r["failedRows"]),
        ("Dynamic: rows in the new table equal source rows",
         f"database {dy['db_row_count']}, source {dy['source_rows']}", dy["db_row_count"] == dy["source_rows"]),
        ("Dynamic: file hash recorded by the system equals an independently computed SHA-256",
         dy["registry_file_hash"][:16] + "…", dy["registry_file_hash"] == dy["sha256"]),
        ("Dynamic: re-upload of the same file is refused",
         dy["duplicate_same_name"].get("status"), dy["duplicate_same_name"].get("status") == "duplicate_file"),
        ("Dynamic: the same content under a new filename is refused",
         f"{dy['duplicate_renamed'].get('status')} (reason: {dy['duplicate_renamed'].get('reason')})",
         dy["duplicate_renamed"].get("status") == "duplicate_file" and dy["duplicate_renamed"].get("reason") == "content"),
        ("Audit: one entry per successful load; refused duplicates leave none",
         f"{au['log']['total']} entries for 2 loads", au["log"]["total"] == 2 and len(entries) == 2),
        ("Audit: hash chain recomputed and intact",
         f"intact={au['verify'].get('intact')}, rows checked={au['verify'].get('rows')}", au["verify"].get("intact") is True),
    ]


def render(ev: dict, rows: list[tuple[str, str, bool]]) -> str:
    te, dy, au, env, po = ev["te"], ev["dynamic"], ev["audit"], ev["environment"], ev["posture"]
    r = te["api"]["response"]
    ok = all(p for _, _, p in rows)
    tick = lambda p: "PASS" if p else "**FAIL**"  # noqa: E731
    out = [
        "# Migration Verification Report: SAMPLE",
        "",
        "> **Sample.** Produced by a real run against a local PostgreSQL instance, using two **synthetic** CSV files "
        "with invented names. It shows the shape and rigour of the report, not a customer migration. "
        "Every figure below was recorded during the run and is reproducible: see section 8.",
        "",
        f"| | |\n|---|---|\n| Run started (UTC) | {ev['started_utc']} |\n| Run finished (UTC) | {ev['finished_utc']} |\n"
        f"| Code version | `{env['code_commit'][:10]}`{' (with local modifications)' if env['tracked_files_modified'] else ' (clean working tree)'} |\n"
        f"| Database | {ev['health'].get('postgres', 'unknown')} |\n"
        f"| Platform | Python {env['python']}, {env['os']} |",
        "",
        "## 1. Result",
        "",
        f"**{'RECONCILED' if ok else 'NOT RECONCILED'}**: {sum(p for _, _, p in rows)} of {len(rows)} checks passed. "
        f"Of {te['source_rows']} source rows in the T&E file, **{r['insertedRows']} were loaded and {r['failedRows']} were rejected by the database**, "
        f"for the reasons in section 4; nothing was lost or silently altered. The {dy['source_rows']}-row dynamic file loaded in full.",
        "",
        "## 2. Source files",
        "",
        "| File | Mode | Rows | Bytes | SHA-256 |\n|---|---|---|---|---|",
        f"| `{te['file']}` | T&E (`organisations`) | {te['source_rows']} | {te['bytes']} | `{te['sha256']}` |",
        f"| `{dy['file']}` | Dynamic | {dy['source_rows']} | {dy['bytes']} | `{dy['sha256']}` |",
        "",
        "## 3. Verification checks",
        "",
        "Each check compares the system's output against the database itself, a hash computed outside the system, or an outcome declared in advance. "
        "The exception is check 12, which is the system recomputing its own audit chain.",
        "",
        "| # | Check | Observed | Result |\n|---|---|---|---|",
        *[f"| {i} | {c} | {o} | {tick(p)} |" for i, (c, o, p) in enumerate(rows, 1)],
        "",
        "## 4. Rejected rows (T&E file)",
        "",
        "The fixture contains four deliberately defective rows. The expected outcome was declared in "
        "`scripts/sample_verification_run.py` before the run. The reason column is the database's own message.",
        "",
        "| Data row | Source line | Designed defect | Database message |\n|---|---|---|---|",
        *[f"| {e['rowNumber']} | `{te['source_lines'][e['rowNumber']]}` "
          f"| {te['expected_rejects'].get(e['rowNumber'], 'not expected')} | {e['reason']} |"
          for e in r.get("rowErrors", [])],
        "",
        "## 5. Rows loaded (T&E file)",
        "",
        f"Read back from `{te['target']}` after the load ({te['db_row_count']} rows):",
        "",
        "| name | org_type | country |\n|---|---|---|",
        *[f"| {a} | {b} | {c.strip()} |" for a, b, c in te["db_rows"]],
        "",
        "## 6. Dynamic mode and duplicate handling",
        "",
        f"`{dy['file']}` created table `{dy['table']}` with {dy['db_row_count']} rows. Column types detected:",
        "",
        "| Column | PostgreSQL type |\n|---|---|",
        *[f"| {n} | {t} |" for n, t in dy["db_columns"]],
        "",
        f"Re-uploading the same file returned `{dy['duplicate_same_name'].get('status')}` "
        f"(reason: `{dy['duplicate_same_name'].get('reason')}`); uploading the same content as "
        f"`equipment_register_copy.csv` returned `{dy['duplicate_renamed'].get('status')}` "
        f"(reason: `{dy['duplicate_renamed'].get('reason')}`). Neither added an audit entry (check 11).",
        "",
        "## 7. Audit trail",
        "",
        f"{au['log']['total']} entries, newest first. The hash chain was recomputed from the stored rows: "
        f"**intact = {au['verify'].get('intact')}** over {au['verify'].get('rows')} rows.",
        "",
        "| Action | File | Target | Mode | Actor | Time (UTC) |\n|---|---|---|---|---|---|",
        *[f"| {e['action']} | {e['fileName']} | {e['tableName']} | {e['mode']} | {e['actor']} | {e['performedAt']} |"
          for e in au["log"]["entries"]],
        "",
        "## 8. What this report does and does not show",
        "",
        "**Shows:** for these two files, every source row is either in the database or rejected with the database's own reason; "
        "loaded values equal source values; file hashes are recorded correctly; duplicates are refused; the audit trail has one entry per successful load and its hash chain verifies.",
        "",
        "**Does not show:**",
        "",
        "- Behaviour on real or large data. The inputs are 10 and 8 invented rows.",
        "- A hardened deployment. Observed during this run: a request with no credentials at all "
        f"returned HTTP **{po['unauthenticated_request_status']}** ({'the API key is not set, so unauthenticated access is open' if po['unauthenticated_request_status'] == 200 else 'access without credentials was refused'}); "
        f"the API's database connections used role(s) **{', '.join(po['database_roles_connected']) or 'unknown'}** "
        f"and the audit table is owned by **{po['audit_log_owner']}**"
        f"{', so the database itself would not stop the API altering the audit log. The audit chain is designed to reveal such changes, but this run did not test that' if po['audit_log_owner'] in po['database_roles_connected'] else ''}.",
        "- Independent assurance. The checks were written and run by the system's developers. They are repeatable by a reviewer, not a third-party assessment.",
        "- Conformance to any Defence standard. No claim of alignment with ASDEFCON or any DID is made here.",
        "- That re-uploading a file is safe. The re-upload case for T&E mode has a known defect, tracked as #215.",
        "",
        "**Reproduce:** deploy the dev schema to an empty database, create a tenant admin, start the API, then run "
        "`python scripts/sample_verification_run.py`. The raw responses behind this report are in "
        "`docs/samples/verification-run-evidence.json`.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--tenant", default="dev")
    ap.add_argument("--username", default="admin")
    args = ap.parse_args()
    password = os.environ.get("TE_ADMIN_PASSWORD")
    if not password:
        print("Set TE_ADMIN_PASSWORD to the tenant admin's password.", file=sys.stderr)
        return 2

    api = Api(args.api)
    status, login = api.call("POST", "/api/auth/login",
                             {"tenant": args.tenant, "username": args.username, "password": password})
    if status != 200:
        print(f"Sign-in failed ({status}): {login}", file=sys.stderr)
        return 2
    api.token = login["token"]

    conn = psycopg2.connect(host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5432"),
                            user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", ""),
                            dbname=os.environ.get("PGDATABASE", "te_mgmt_dev"))
    conn.autocommit = True
    ev = collect(api, conn)
    rows = checks(ev)

    (SAMPLES / "verification-run-evidence.json").write_text(json.dumps(ev, indent=2, default=str) + "\n", encoding="utf-8")
    (SAMPLES / "MIGRATION_VERIFICATION_REPORT_SAMPLE.md").write_text(render(ev, rows), encoding="utf-8")
    for c, o, p in rows:
        print(("PASS" if p else "FAIL"), "-", c, "->", o)
    return 0 if all(p for _, _, p in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
