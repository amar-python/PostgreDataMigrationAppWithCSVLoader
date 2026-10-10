"""Fixtures for the accessibility suite: a Vite dev server for the React
frontend, a headless Chromium via Playwright, and a mocked backend.

The backend is mocked with Playwright request interception, so these tests
need neither PostgreSQL nor the FastAPI process — only Node (with
csv-table-hub-main/node_modules installed) and a Playwright Chromium.

Prerequisites (missing ones FAIL with remediation, per the no-skip policy):
    (cd csv-table-hub-main && bun install)       # or npm install
    pip install -r requirements-dev.txt          # playwright + axe-playwright-python
    python -m playwright install chromium        # skip if PLAYWRIGHT_BROWSERS_PATH is set up

Environment knobs:
    A11Y_BASE_URL  test an already-running frontend instead of starting Vite
    A11Y_PORT      port for the Vite dev server this fixture starts (default 8089)
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess  # nosec B404 — starts the local Vite dev server
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "csv-table-hub-main"

TE_TABLES = [
    "organisations", "personnel", "test_programs", "temp_documents", "test_phases",
    "requirements", "test_cases", "vcrm_entries", "test_events", "test_results",
    "defect_reports", "evidence_artifacts",
]

MOCK_FILES = [
    {
        "id": str(i),
        "file_name": f"customers_{i:02d}.csv",
        "table_name": f"csv_{i:016x}",
        "mode": "dynamic",
        "row_count": 10 * i,
        "column_names": ["id", "name", "email", "signup_date"],
        "created_at": f"2026-09-{(i % 28) + 1:02d}T10:00:00+00:00",
    }
    for i in range(1, 61)  # 60 files: two pages at the default page size of 50
]

MOCK_ROWS = {"rows": [
    {"_id": 1, "id": 1, "name": "Alice Nguyen", "email": "alice@example.com",
     "signup_date": "2024-01-15", "_row_hash": "a" * 64, "_created_at": "2026-09-01T10:00:00+00:00"},
]}

MOCK_PREVIEW = {
    "status": "ok", "headers": ["name", "org_type", "country"],
    "columns": ["name", "org_type", "country"], "inferredTypes": ["text", "text", "text"],
    "sampleRows": [["ACME", "prime", "AU"]], "totalRowsApprox": 1, "teTableMatch": "organisations",
}

MOCK_UPLOAD = {
    "status": "ok", "fileId": "99", "tableName": "csv_00000000000000ff", "totalRows": 3,
    "insertedRows": 2, "duplicateRowsSkipped": 0, "failedRows": 1,
    "columns": ["name", "org_type", "country"], "types": ["text", "text", "text"],
    "rowErrors": [{"rowNumber": 3, "column": "country", "value": "AUS", "reason": "too long"}],
    "logs": [{"ts": 1, "step": "done", "level": "info", "message": "Import complete"}],
    "overwritten": False, "replacedFileName": None,
}

# A finished job history as the upload page persists it (useLocalStorageState).
MOCK_JOBS = [
    {"id": "j1", "batchId": "b1", "name": "customers.csv", "size": 2048, "status": "done",
     "progress": 100, "createdAt": 1_790_000_000_000, "insertedRows": 5, "totalRows": 5,
     "failedRows": 0, "duplicateRowsSkipped": 0, "tableName": "csv_0000000000000001",
     "mode": "dynamic"},
    {"id": "j2", "batchId": "b1", "name": "orders.csv", "size": 4096, "status": "error",
     "progress": 100, "createdAt": 1_790_000_100_000, "errorMessage": "Unsupported column type",
     "rowErrors": [{"rowNumber": 2, "column": "qty", "value": "two", "reason": "not a number"}],
     "mode": "dynamic"},
    {"id": "j3", "batchId": "b2", "name": "inventory.csv", "size": 1024, "status": "duplicate",
     "progress": 100, "createdAt": 1_790_000_200_000, "existingFileName": "inventory.csv",
     "duplicateReason": "content", "tableName": "csv_0000000000000003", "mode": "dynamic"},
]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def frontend_url():
    """URL of a running frontend; starts `vite dev` unless A11Y_BASE_URL is set."""
    external = os.environ.get("A11Y_BASE_URL")
    if external:
        yield external.rstrip("/")
        return

    if not (FRONTEND / "node_modules").is_dir():
        pytest.fail(
            "csv-table-hub-main/node_modules is missing — install the frontend first:\n"
            "    cd csv-table-hub-main && bun install   (or npm install)",
            pytrace=False,
        )
    npx = shutil.which("npx")
    if not npx:
        pytest.fail("Node.js (npx) is not on PATH — install Node 22+.", pytrace=False)

    port = int(os.environ.get("A11Y_PORT", "8089"))
    if _port_open(port):
        pytest.fail(f"Port {port} is already in use — set A11Y_PORT or A11Y_BASE_URL.",
                    pytrace=False)

    env = {**os.environ, "VITE_API_BASE": "", "VITE_API_KEY": "", "BROWSER": "none"}
    log = open(Path(os.environ.get("TMPDIR", "/tmp")) / "a11y-vite.log", "w")  # noqa: SIM115
    # The TanStack router plugin regenerates routeTree.gen.ts on start; keep
    # the committed copy so a local test run leaves the working tree clean.
    route_tree = FRONTEND / "src" / "routeTree.gen.ts"
    route_tree_before = route_tree.read_bytes() if route_tree.exists() else None
    # New session => own process group, so the vite child that npx spawns is
    # stopped too (terminating npx alone orphans it and leaks the port).
    proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
        [npx, "vite", "dev", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=FRONTEND, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 120
    try:
        while True:
            if proc.poll() is not None:
                pytest.fail(f"vite dev exited early (code {proc.returncode}); see {log.name}",
                            pytrace=False)
            try:
                with urllib.request.urlopen(url + "/audit", timeout=5) as r:  # nosec B310 — localhost
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"vite dev did not answer on {url} within 120s; see {log.name}",
                            pytrace=False)
            time.sleep(1)
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
        if route_tree_before is not None and route_tree.read_bytes() != route_tree_before:
            route_tree.write_bytes(route_tree_before)


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.fail("playwright is not installed — pip install -r requirements-dev.txt",
                    pytrace=False)
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"Could not launch Chromium: {str(exc).splitlines()[0]}\n"
                "    python -m playwright install --with-deps chromium",
                pytrace=False,
            )
        yield b
        b.close()


def _json(route, payload, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _mock_api(route):
    """Answer every /api/* call the frontend makes with realistic fixtures."""
    req = route.request
    path = req.url.split("/api/", 1)[1].split("?", 1)[0]
    if path == "csv/files":
        return _json(route, MOCK_FILES)
    if path == "te/tables":
        return _json(route, [{"table": t, "exists": True, "rowCount": 3} for t in TE_TABLES])
    if path.startswith("csv/tables/"):
        return _json(route, MOCK_ROWS)
    if path == "csv/preview":
        return _json(route, MOCK_PREVIEW)
    if path == "csv/upload":
        return _json(route, MOCK_UPLOAD)
    if path == "health":
        return _json(route, {"status": "ok"})
    return _json(route, {"detail": "not mocked"}, 404)


@pytest.fixture
def page(browser, frontend_url):
    """A fresh page with the API mocked and an import history seeded."""
    context = browser.new_context(base_url=frontend_url, viewport={"width": 1280, "height": 900})
    context.add_init_script(
        f"window.localStorage.setItem('csv-migrator:jobs:v1', {json.dumps(json.dumps(MOCK_JOBS))});"
    )
    context.route("**/api/**", _mock_api)
    pg = context.new_page()
    pg.set_default_timeout(30_000)
    yield pg
    context.close()
