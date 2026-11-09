"""Browser end-to-end tests: the real API, the real React app and the Streamlit spike, in Chromium.

Not collected by the default `pytest` run (testpaths = tests): they need Node dependencies, a
browser and three local servers. See e2e/README.md.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, sync_playwright
from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import db  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import Conn  # noqa: E402
from api.services import accounts  # noqa: E402
from api.tenancy import migrate_tenant, schema_for  # noqa: E402

API_PORT, WEB_PORT, ST_PORT = 8000, 8080, 8501
PASSWORD = "e2e correct horse battery"
REMEDY = "stop whatever listens on it (or the previous run's servers) and rerun"


@dataclass
class Account:
    tenant: str
    username: str
    role: str


@dataclass
class Stack:
    api: str
    web: str
    streamlit: str
    accounts: dict[str, Account] = field(default_factory=dict)

    def token(self, who: str) -> str:
        a = self.accounts[who]
        res = requests.post(f"{self.api}/api/auth/login", timeout=30,
                            json={"tenant": a.tenant, "username": a.username, "password": PASSWORD})
        res.raise_for_status()
        return res.json()["token"]

    def upload(self, who: str, name: str, content: str, **extra) -> dict:
        res = requests.post(f"{self.api}/api/csv/upload", timeout=60,
                            headers={"Authorization": f"Bearer {self.token(who)}"},
                            json={"fileName": name, "content": content, **extra})
        res.raise_for_status()
        return res.json()


def _port_is_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_for(url: str, what: str, seconds: int = 120) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=3).status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError(f"{what} did not come up at {url} within {seconds}s")


@pytest.fixture(scope="session")
def stack():
    for port in (API_PORT, WEB_PORT, ST_PORT):
        if not _port_is_free(port):
            raise RuntimeError(f"port {port} is in use: {REMEDY}")
    if not (ROOT / "csv-table-hub-main/node_modules").exists():
        raise RuntimeError("run `npm ci` in csv-table-hub-main first")

    db.init_pool()  # as scripts/create_tenant_admin.py does, outside the API process
    db.bootstrap()
    tag = f"{os.getpid()}_{uuid.uuid4().hex[:5]}"
    accts = {
        "admin": Account(f"e2ea_{tag}", f"admin_{tag}", "tenant_admin"),
        "uploader": Account(f"e2ea_{tag}", f"uploader_{tag}", "uploader"),
        "reviewer": Account(f"e2ea_{tag}", f"reviewer_{tag}", "reviewer"),
        "other": Account(f"e2eb_{tag}", f"other_{tag}", "tenant_admin"),
    }
    with Conn() as conn, conn.cursor() as cur:
        tenant_ids = {t: accounts.create_tenant(cur, t, t) for t in {a.tenant for a in accts.values()}}
        for a in accts.values():
            accounts.add_membership(cur, accounts.create_user(cur, a.username, PASSWORD), tenant_ids[a.tenant], a.role)
        conn.commit()
    for t in tenant_ids:
        migrate_tenant(t)

    api, web, st = (f"http://127.0.0.1:{p}" for p in (API_PORT, WEB_PORT, ST_PORT))
    env = {**os.environ, "CORS_ORIGINS": web, "API_RATE_LIMIT_WRITES": "0", "API_RATE_LIMIT_READS": "0"}
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "csv-table-hub-main", check=True, capture_output=True,
                   env={**env, "NITRO_PRESET": "node-server", "VITE_API_BASE": api})  # VITE_API_BASE is baked in
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(API_PORT)],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True),
        # The production build, served as the offline bundle serves it: what ships, not the dev server.
        subprocess.Popen(["node", ".output/server/index.mjs"], cwd=ROOT / "csv-table-hub-main",
                         env={**env, "PORT": str(WEB_PORT), "HOST": "127.0.0.1"},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True),
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "spikes/streamlit_review/app.py",
                          "--server.headless", "true", "--server.port", str(ST_PORT),
                          "--browser.gatherUsageStats", "false"],
                         cwd=ROOT, env={**env, "API_URL": api}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True),
    ]
    try:
        _wait_for(f"{api}/api/health", "the API")
        _wait_for(f"{web}/auth", "the React app")
        _wait_for(f"{st}/_stcore/health", "Streamlit")
        yield Stack(api, web, st, accts)
    finally:
        for p in procs:  # each server leads its own process group, so npx's child dies with it
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        with Conn() as conn, conn.cursor() as cur:
            for t in tenant_ids:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(t))))
                cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (t,))
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s OR username LIKE %s OR username LIKE %s "
                                "OR username LIKE %s").format(sql.Identifier(settings.CONTROL_SCHEMA)),
                        tuple(f"{p}_{tag}" for p in ("admin", "uploader", "reviewer", "other")))
            conn.commit()
        db.close_pool()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        exe = os.environ.get("E2E_CHROMIUM") or None  # else the browser `playwright install` fetched
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
    ctx.set_default_timeout(20_000)
    pg = ctx.new_page()
    yield pg
    ctx.close()


def react_sign_in(page: Page, stack: Stack, who: str) -> None:
    a = stack.accounts[who]
    page.goto(f"{stack.web}/auth")
    page.get_by_label("Tenant").fill(a.tenant)
    page.get_by_label("Username").fill(a.username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("button", name="Sign out").wait_for()


def streamlit_sign_in(page: Page, stack: Stack, who: str) -> None:
    a = stack.accounts[who]
    page.goto(stack.streamlit)
    side = page.locator('[data-testid="stSidebar"]')
    side.get_by_label("Tenant").fill(a.tenant)
    side.get_by_label("Username").fill(a.username)
    side.get_by_role("textbox", name="Password").fill(PASSWORD)
    side.get_by_role("button", name="Sign in").click()
    side.get_by_text(a.role, exact=True).wait_for()
