#!/usr/bin/env python3
"""Smoke test for the container install (#128, BR-38): 7 checks, PASS/FAIL per check.

A port of scripts/offline/smoke_test.sh to the standard library, so it runs inside the
API container and needs nothing on the host: no curl or bash, which a Windows machine
does not have. The installer runs it with `compose exec`.

Every data call signs in first: the shared API key was retired (#298).

Environment:
  SMOKE_TENANT, SMOKE_USER, SMOKE_PASSWORD   the first tenant admin, created by the installer.
                   The test signs in as this admin for checks 3 to 6. If any is missing, those
                   four cannot run, and that is a FAIL, not a skip (the repository rule): the
                   result is then at most "3 of 7" and the exit code non-zero.
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
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"the smoke test only calls http(s) URLs, got {url!r}")  # urlopen would follow file:
    data = None if body is None else json.dumps(body).encode()
    hdrs = dict(headers or {})
    if data is not None:
        hdrs["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 # scheme checked at the top
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
    tenant, user, password = (os.environ.get(n, "") for n in ("SMOKE_TENANT", "SMOKE_USER", "SMOKE_PASSWORD"))
    with_login = bool(tenant and user and password)
    total = TOTAL

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
    check("API rejects a request without a session", status == 401, f"got HTTP {status}")

    if with_login:
        status, text = call(f"{API}/api/auth/login", method="POST",
                            body={"tenant": tenant, "username": user, "password": password})
        token = ""
        try:
            token = json.loads(text).get("token", "") if status == 200 else ""
        except ValueError:
            pass
        check("admin signs in", bool(token), f"HTTP {status}")
        auth = {"Authorization": f"Bearer {token}"}

        status, text = call(f"{API}/api/auth/me", headers=auth)
        check("session is tenant_admin", status == 200 and '"role":"tenant_admin"' in compact(text),
              f"HTTP {status}")

        tag = time.time_ns()  # unique name and content, so the test can be re-run
        name = f"smoke_{tag}.csv"
        status, text = call(f"{API}/api/csv/upload", method="POST", headers=auth,
                            body={"fileName": name, "content": f"a,b\n1,{tag}\n2,y\n"})
        check("upload a CSV (2 rows inserted)", '"insertedRows":2' in compact(text), f"HTTP {status}: {text[:200]}")

        status, text = call(f"{API}/api/csv/files", headers=auth)
        check("upload listed with persisted counts", status == 200 and '"total_rows":2' in compact(text),
              f"HTTP {status}")
    else:
        # Counted as the four checks it stands for, so the run reports "3 of 7", never a pass.
        print("FAIL  sign-in, upload and listing checks: set SMOKE_TENANT, SMOKE_USER and SMOKE_PASSWORD "
              "(the installer's first tenant admin)")

    status, text = call(f"{FRONTEND}/")
    check("frontend serves the app", status == 200 and "<html" in text.lower(), f"HTTP {status}")

    print(f"{passed} of {total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
