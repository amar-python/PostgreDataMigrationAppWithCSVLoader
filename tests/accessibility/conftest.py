"""Playwright fixtures for the accessibility scans (#168).

What a scan needs: the frontend (csv-table-hub-main) served by the Vite dev server, a
Chromium, and axe-core. The API is stubbed (tests/accessibility/stub_api.py), so there is
no database and no API process.

Everything heavy is imported inside a fixture, never at module level. ``tests/`` is
collected as a whole by other jobs and by developers who never scan; collecting this
folder must not need Playwright. A missing prerequisite FAILS the test with what to run
(this project's policy: unmet prerequisites are failures, never skips).

Environment
-----------
A11Y_BASE_URL       scan an already running frontend instead of starting ``npm run dev``
                    (React scans only; the Streamlit scans always start their own app)
A11Y_CHROMIUM_PATH  use this Chromium instead of the one ``playwright install`` fetched
A11Y_REPORT_DIR     write one JSON file per scenario with every violation axe found
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.accessibility import axe_baseline, stub_api

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "csv-table-hub-main"
STARTUP_TIMEOUT_S = 180   # first start also pre-bundles dependencies


def _fail(message: str):
    raise AssertionError(message)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_serving(url: str, proc: subprocess.Popen | None, log: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            _fail(f"The frontend dev server exited with code {proc.returncode} before serving.\n"
                  f"{log.read_text(errors='replace')[-2000:]}")
        try:
            with urllib.request.urlopen(f"{url}/auth", timeout=5) as res:
                if res.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    _fail(f"The frontend did not serve {url}/auth within {STARTUP_TIMEOUT_S}s.\n"
          f"{log.read_text(errors='replace')[-2000:] if log.exists() else ''}")


@pytest.fixture(scope="session")
def app_url():
    """Base URL of the frontend: A11Y_BASE_URL, or a Vite dev server started for the session."""
    given = os.environ.get("A11Y_BASE_URL")
    if given:
        url = given.rstrip("/")
        _wait_until_serving(url, None, Path(os.devnull))
        yield url
        return

    npm = shutil.which("npm")
    if not npm:
        _fail("npm was not found. Install Node.js 22 to serve the frontend for the scans.")
    if not (FRONTEND / "node_modules").is_dir():
        _fail(f"The frontend's dependencies are not installed. Run: (cd {FRONTEND.name} && npm ci)")

    port = _free_port()
    log = Path(tempfile.mkdtemp(prefix="a11y-vite-")) / "vite.log"
    with log.open("wb") as out:
        proc = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=FRONTEND, stdout=out, stderr=subprocess.STDOUT,
            # An empty API base makes the app call /api on its own origin, where the
            # stub answers. A new session lets teardown stop npm, vite and their children.
            env={**os.environ, "VITE_API_BASE": "", "BROWSER": "none"},
            start_new_session=(os.name == "posix"),
        )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_serving(url, proc, log)
        yield url
    finally:
        if proc.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                proc.kill()


@pytest.fixture(scope="session")
def a11y_browser(app_url):
    """One Chromium for the session, warmed up so Vite's first-load dependency
    pre-bundling (which reloads the page once) cannot land in the middle of a scan."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail("Playwright is not installed. Run: pip install -r requirements-a11y.txt "
              "&& python -m playwright install chromium")
    pw = sync_playwright().start()
    try:
        launch = {}
        if os.environ.get("A11Y_CHROMIUM_PATH"):
            launch["executable_path"] = os.environ["A11Y_CHROMIUM_PATH"]
        try:
            browser = pw.chromium.launch(**launch)
        except Exception as exc:  # noqa: BLE001
            _fail(f"Chromium could not start: {exc}\nRun: python -m playwright install chromium")
        warm = browser.new_context()
        warm.add_init_script(stub_api.seed_script(stub_api.SESSION, stub_api.JOBS))
        warm.route("**/api/**", stub_api.handler(stub_api.default_responses(), []))
        page = warm.new_page()
        for path in ("/auth", "/", "/audit", "/review/101"):
            try:
                page.goto(app_url + path, wait_until="networkidle", timeout=120_000)
            except Exception:  # noqa: BLE001  the scenarios report a page that really fails
                pass
        warm.close()
        yield browser
        browser.close()
    finally:
        pw.stop()


@pytest.fixture
def open_page(a11y_browser, app_url, request):
    """``open_page(path, ...)`` -> a Page on the frontend with the stubbed API.

    signed_in  plant a session (the pages under / need one)
    jobs       import history to show (see stub_api.seed_script); None for none
    responses  extra or replacement API responses, route -> body or callable
    """
    contexts = []
    unstubbed: list[str] = []

    def _open(path: str, *, signed_in: bool = True, jobs: list[dict] | None = None,
              responses: stub_api.Responses | None = None):
        context = a11y_browser.new_context(
            viewport={"width": 1280, "height": 900}, locale="en-AU", timezone_id="UTC",
            color_scheme="light",
            # Animations change what is on screen mid-scan (and what contrast is measured on).
            reduced_motion="reduce",
        )
        contexts.append(context)
        script = stub_api.seed_script(stub_api.SESSION if signed_in else None, jobs)
        if script:
            context.add_init_script(script)
        context.route("**/api/**", stub_api.handler({**stub_api.default_responses(), **(responses or {})},
                                                    unstubbed))
        page = context.new_page()
        page.goto(app_url + path, wait_until="networkidle", timeout=60_000)
        return page

    yield _open
    for context in contexts:
        context.close()
    # A request the stub did not know is a page asking for something these scans never
    # looked at; say so rather than scanning a page that may be half empty.
    assert not unstubbed, f"The page called API routes the accessibility stub has no answer for: {unstubbed}"


@pytest.fixture
def scan():
    """``scan(page, scenario)``: run axe-core (WCAG 2.1 A and AA) and judge the result
    against known_violations.json. Fails on a new violation or a fixed-but-still-listed one."""
    try:
        from axe_playwright_python.sync_playwright import Axe
    except ImportError:
        _fail("axe-playwright-python is not installed. Run: pip install -r requirements-a11y.txt")
    baseline = axe_baseline.load_baseline()

    def _scan(page, scenario: str) -> axe_baseline.Outcome:
        page.wait_for_load_state("networkidle")
        # A dialog still fading in is blended with the page behind it, so axe reads false
        # colour-contrast failures. Let every running animation finish before scanning.
        page.evaluate("Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})))")
        result = Axe().run(page, options={"runOnly": {"type": "tag", "values": axe_baseline.WCAG_21_AA_TAGS}})
        violations = result.response["violations"]
        outcome = axe_baseline.compare(scenario, violations, baseline)

        report_dir = os.environ.get("A11Y_REPORT_DIR")
        if report_dir:
            Path(report_dir).mkdir(parents=True, exist_ok=True)
            (Path(report_dir) / f"{scenario}.json").write_text(
                json.dumps({"scenario": scenario, "url": page.url, "violations": violations,
                            "known": outcome.known, "shrunk": outcome.shrunk}, indent=2),
                encoding="utf-8")

        for line in outcome.known + outcome.shrunk:
            print(f"[a11y {scenario}] {line}")
        problems = outcome.new + outcome.fixed
        assert not problems, f"[{scenario}] accessibility baseline changed:\n" + "\n".join(problems)
        return outcome

    return _scan


# --- Streamlit -------------------------------------------------------------------------------------
# Streamlit calls the API from its Python server, so the browser-side route stub cannot answer for it.
# The same stub data is served over real HTTP, and the app is pointed at it with API_URL.

STREAMLIT_APP = ROOT / "streamlit_app"


@pytest.fixture(scope="session")
def stub_api_url():
    """A local HTTP server answering with stub_api's data (any method). Sign in with stub_api.STREAMLIT_PASSWORD."""
    responses = {**stub_api.default_responses(), "/api/csv/uploads": stub_api.UPLOADS}

    class Handler(BaseHTTPRequestHandler):
        def _answer(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            path = self.path.split("?")[0]
            if self.command == "POST" and path == "/api/auth/login" \
                    and json.loads(body or b"{}").get("password") == stub_api.STREAMLIT_PASSWORD:
                status, payload = 200, stub_api.STREAMLIT_SESSION
            else:
                status, payload = stub_api.respond(path, responses)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = _answer

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def streamlit_url(stub_api_url):
    """Base URL of the Streamlit app, started for the session against the stub API."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        _fail("Streamlit is not installed. Run: pip install -r streamlit_app/requirements.txt")
    port = _free_port()
    log = Path(tempfile.mkdtemp(prefix="a11y-streamlit-")) / "streamlit.log"
    with log.open("wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
             "--server.address", "127.0.0.1", "--server.headless", "true"],
            cwd=STREAMLIT_APP, stdout=out, stderr=subprocess.STDOUT,
            env={**os.environ, "API_URL": stub_api_url}, start_new_session=(os.name == "posix"),
        )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            if proc.poll() is not None:
                _fail(f"Streamlit exited with code {proc.returncode} before serving.\n"
                      f"{log.read_text(errors='replace')[-2000:]}")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=5) as res:
                    if res.read().strip() == b"ok":
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                _fail(f"Streamlit did not report healthy at {url} within 60s.\n{log.read_text(errors='replace')[-2000:]}")
            time.sleep(0.5)
        yield url
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM) if os.name == "posix" else proc.terminate()
                proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                proc.kill()


@pytest.fixture
def streamlit_page(streamlit_url):
    """``streamlit_page(sign_in=True)`` -> a Page on the Streamlit app, signed in through the real form unless told not to."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail("Playwright is not installed. Run: pip install -r requirements-a11y.txt "
              "&& python -m playwright install chromium")
    pw = sync_playwright().start()
    browser = None
    try:
        launch = {}
        if os.environ.get("A11Y_CHROMIUM_PATH"):
            launch["executable_path"] = os.environ["A11Y_CHROMIUM_PATH"]
        try:
            browser = pw.chromium.launch(**launch)
        except Exception as exc:  # noqa: BLE001
            _fail(f"Chromium could not start: {exc}\nRun: python -m playwright install chromium")
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-AU",
                                      timezone_id="UTC", color_scheme="light", reduced_motion="reduce")

        def _open(*, sign_in: bool = True):
            page = context.new_page()
            page.goto(streamlit_url, wait_until="networkidle", timeout=60_000)
            if sign_in:
                sign_in_as(page, stub_api.STREAMLIT_PASSWORD)
                page.get_by_text("What your role can do").wait_for(state="visible", timeout=15_000)
            return page

        yield _open
    finally:
        if browser:
            browser.close()
        pw.stop()


def sign_in_as(page, password: str) -> None:
    page.get_by_label("Tenant").fill("acme")
    page.get_by_label("Username").fill("ada")
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()
