#!/usr/bin/env python3
"""Smoke test for the container install (#128, BR-38): 7 checks, PASS/FAIL per check.

A port of scripts/offline/smoke_test.sh to the standard library, so it runs inside the
API container and needs nothing on the host: no curl or bash, which a Windows machine
does not have. The installer runs it with `compose exec`.

Environment:
  API_KEY          the deployment's key (required)
  SMOKE_TENANT, SMOKE_USER, SMOKE_PASSWORD   the first tenant admin: checks 6 and 7. If any
                   is missing (a re-run of the installer no longer knows the password), those
                   two are skipped and the test reports "5 of 5"; the full result is 7 of 7.
  API_URL          default http://localhost:8000   (the API, from inside its container)
  FRONTEND_URL     default http://frontend:8080    (the frontend, over the compose network)

Exits 0 only if every check that ran passed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
FRONTEND = os.environ.get("FRONTEND_URL", "http://frontend:8080").rstrip("/")
TOTAL = 7


def call(url: str, *, method: str = "GET", headers: dict | None = None, body: dict | None = None,
         timeout: float = 15.0) -> tuple[int, str]:
    """Return (status, text). An HTTP error is a status, not an exception."""
    data = None if body is None else json.dumps(body).encode()
    hdrs = dict(headers or {})
    if data is not None:
        hdrs["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_for(url: str, seconds: int = 90) -> bool:
    """Services may still be starting: wait for the first successful answer."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if call(url, timeout=3.0)[0] < 500:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def compact(text: str) -> str:
    """Re-serialise JSON compactly, so a substring test does not depend on spacing."""
    try:
        return json.dumps(json.loads(text), separators=(",", ":"))
    except ValueError:
        return text


def main() -> int:
    key = os.environ.get("API_KEY", "")
    tenant, user, password = (os.environ.get(n, "") for n in ("SMOKE_TENANT", "SMOKE_USER", "SMOKE_PASSWORD"))
    if not key:
        print("API_KEY must be set", file=sys.stderr)
        return 2
    with_login = bool(tenant and user and password)
    total = TOTAL if with_login else TOTAL - 2

    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not detail else f": {detail}"))
        passed += ok

    wait_for(f"{API}/api/health")
    wait_for(f"{FRONTEND}/")

    status, _ = call(f"{API}/api/health")
    check("API health", status == 200, f"HTTP {status}")

    status, _ = call(f"{API}/api/csv/files")
    check("API rejects a missing key", status == 401, f"got HTTP {status}")

    tag = time.time_ns()  # unique name and content, so the test can be re-run
    name = f"smoke_{tag}.csv"
    status, text = call(f"{API}/api/csv/upload", method="POST", headers={"X-API-Key": key},
                        body={"fileName": name, "content": f"a,b\n1,{tag}\n2,y\n"})
    check("upload a CSV (2 rows inserted)", '"insertedRows":2' in compact(text), f"HTTP {status}: {text[:200]}")

    status, text = call(f"{API}/api/csv/files", headers={"X-API-Key": key})
    check("upload listed with persisted counts", status == 200 and '"total_rows":2' in compact(text),
          f"HTTP {status}")

    status, text = call(f"{FRONTEND}/")
    check("frontend serves the app", status == 200 and "<html" in text.lower(), f"HTTP {status}")

    if with_login:
        status, text = call(f"{API}/api/auth/login", method="POST",
                            body={"tenant": tenant, "username": user, "password": password})
        token = ""
        try:
            token = json.loads(text).get("token", "") if status == 200 else ""
        except ValueError:
            pass
        check("admin signs in", bool(token), f"HTTP {status}")

        status, text = call(f"{API}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        check("session is tenant_admin", status == 200 and '"role":"tenant_admin"' in compact(text),
              f"HTTP {status}")
    else:
        print("SKIP  admin sign-in checks (SMOKE_TENANT, SMOKE_USER and SMOKE_PASSWORD not all set)")

    print(f"{passed} of {total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
