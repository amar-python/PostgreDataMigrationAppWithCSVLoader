"""#307 (OIT-022, BR-58, M0 decision 1): at most 4 imports run at once on one API instance.

Every upload, stage and import request holds a database connection for its whole load, and the pool has 8 (and sign-in
and every other request borrow one too). With nothing limiting imports, a handful of slow ones starve everyone else,
who then get "Server busy" after the pool timeout. Asserted here, with no database (the loaders are replaced by a stand-in
that holds its callers until released, and the real routes, auth and middleware are used):

  * the helper admits ``MAX_CONCURRENT_IMPORTS`` requests and refuses the next with 503, a clear message and
    ``Retry-After``; a slot frees when its request ends, also when it fails; ``0`` turns the limit off; the limit is read
    at call time;
  * on each of ``POST /api/csv/upload``, ``POST /api/csv/uploads`` (stage) and ``POST /api/csv/uploads/{id}/import``:
    4 concurrent requests are admitted, the 5th gets the 503, and after they finish a new one is admitted;
  * a request that fails authentication is refused with 401 before it is counted, so a saturated server does not reveal
    its load to anyone without a key; the slot comes after the permission check on each route;
  * a preview (no database) is not limited.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import concurrency
from api.config import Settings, settings
from api.main import app
from api.routers import csv_routes, import_routes
from api.services import staged_import

pytestmark = [pytest.mark.unit, pytest.mark.regression]

CSV = {"fileName": "a.csv", "content": "a,b\n1,2\n"}


# -- the helper -------------------------------------------------------------------------------------------------------


def take(n: int):
    """Hold ``n`` slots, as ``n`` requests in flight would; returns the open dependency generators."""
    held = []
    for _ in range(n):
        gen = concurrency.import_slot()
        next(gen)
        held.append(gen)
    return held


def release(held) -> None:
    for gen in held:
        gen.close()


@pytest.fixture(autouse=True)
def limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 4)
    yield
    assert concurrency.active_imports() == 0, "a test left a slot taken"


def test_the_default_is_four():
    assert os.environ.get("API_MAX_CONCURRENT_IMPORTS") is None, "this check is about the shipped default"
    # A configuration built from an empty environment, so the fixture's patch of the shared instance cannot hide it.
    assert Settings.from_env({}).MAX_CONCURRENT_IMPORTS == 4


def test_it_admits_the_limit_and_refuses_the_next_with_503_and_retry_after():
    held = take(4)
    try:
        with pytest.raises(HTTPException) as refused:
            next(concurrency.import_slot())
        exc = refused.value
        assert exc.status_code == 503
        assert "Too many imports" in exc.detail and "4" in exc.detail, exc.detail
        assert exc.headers["Retry-After"].isdigit() and int(exc.headers["Retry-After"]) >= 1
        assert concurrency.active_imports() == 4, "a refused request must not take a slot"
    finally:
        release(held)


def test_a_slot_frees_when_its_request_ends():
    held = take(4)
    held.pop().close()
    again = take(1)  # does not raise
    release(held + again)


def test_a_slot_frees_when_its_request_fails():
    held = take(4)
    failing = held.pop()
    with pytest.raises(ValueError):
        failing.throw(ValueError("the load failed"))
    again = take(1)
    release(held + again)


def test_zero_turns_the_limit_off(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 0)
    held = take(20)
    assert concurrency.active_imports() == 0, "nothing is counted when there is no limit"
    release(held)


def test_the_limit_is_read_when_a_request_arrives(monkeypatch):
    held = take(2)
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 2)
    with pytest.raises(HTTPException):
        next(concurrency.import_slot())
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 3)
    held += take(1)
    release(held)


def test_lowering_the_limit_while_requests_run_does_not_leak_slots(monkeypatch):
    held = take(3)
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 0)  # the 3 were counted; they must still be released
    release(held)
    assert concurrency.active_imports() == 0


# -- the real routes -------------------------------------------------------------------------------------------------


class Loader:
    """Stands in for a loader: counts the callers inside it and holds them until released."""

    def __init__(self, result: dict):
        self.result = result
        self.release = threading.Event()
        self.entered = 0
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        with self._lock:
            self.entered += 1
        self.release.wait(20)
        return dict(self.result)

    def wait_for(self, n: int) -> None:
        deadline = time.monotonic() + 15
        while self.entered < n:
            assert time.monotonic() < deadline, f"only {self.entered} of {n} requests reached the loader"
            time.sleep(0.01)


ROUTES = {
    "import": ("/api/csv/uploads/1/import", None),
    "upload": ("/api/csv/upload", {**CSV, "mode": "dynamic"}),
    "stage": ("/api/csv/uploads", CSV),
}


@pytest.fixture
def loader(monkeypatch):
    """One stand-in behind all three routes (so each test names the route and nothing else)."""
    stand_in = Loader({"status": "staged"})
    monkeypatch.setattr(staged_import, "import_upload", stand_in)  # POST .../uploads/{id}/import
    monkeypatch.setattr(import_routes, "_run", stand_in)  # POST .../uploads (stage)
    monkeypatch.setattr(csv_routes, "upload_dynamic", stand_in)  # POST .../upload
    monkeypatch.setattr(csv_routes, "record_upload", lambda *a, **k: None)
    return stand_in


def post(client: TestClient, route: str, headers: dict | None = None):
    url, body = ROUTES[route]
    return client.post(url, json=body, headers=headers or {})


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_the_fifth_concurrent_import_is_refused_and_a_later_one_is_admitted(route, loader):
    client = TestClient(app, raise_server_exceptions=False)
    stand_in = loader
    with ThreadPoolExecutor(4) as pool:
        running = [pool.submit(post, client, route) for _ in range(4)]
        stand_in.wait_for(4)
        refused = post(client, route)
        assert refused.status_code == 503, (refused.status_code, refused.text)
        assert "Too many imports" in refused.json()["detail"]
        assert refused.headers["Retry-After"].isdigit()
        stand_in.release.set()
        statuses = [f.result().status_code for f in running]
    assert 503 not in statuses, f"the four admitted requests were not all served: {statuses}"
    assert post(client, route).status_code != 503, "a slot must be free once the others have finished"
    assert concurrency.active_imports() == 0


def test_with_the_limit_off_nothing_is_refused(loader, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_IMPORTS", 0)
    client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(6) as pool:
        running = [pool.submit(post, client, "import") for _ in range(6)]
        loader.wait_for(6)
        loader.release.set()
        assert 503 not in [f.result().status_code for f in running]


def test_a_failed_authentication_is_refused_before_it_is_counted(loader, monkeypatch):
    """With the server full, a caller who has not signed in learns nothing about its load: it gets the usual 401.

    The four imports that fill the server get in under the suite's anonymous opt-in; it is then switched off, so the
    next callers (one with a retired X-API-Key header, one with nothing) must sign in (#298).
    """
    client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(4) as pool:
        running = [pool.submit(post, client, "import") for _ in range(4)]
        loader.wait_for(4)
        monkeypatch.setattr(settings, "API_ALLOW_ANONYMOUS", False)
        wrong = post(client, "import", {"X-API-Key": "anything"})
        none = post(client, "import")
        loader.release.set()
        [f.result() for f in running]
    assert (wrong.status_code, none.status_code) == (401, 401)


def test_a_preview_is_not_limited(loader):
    client = TestClient(app, raise_server_exceptions=False)
    held = take(4)
    try:
        res = client.post("/api/csv/preview", json=CSV)
        assert res.status_code == 200, res.text
    finally:
        release(held)


@pytest.mark.parametrize("path", sorted(url for url, _ in ROUTES.values()))
def test_the_slot_is_taken_after_authentication_and_the_permission_check(path):
    # Included routers are not flattened into app.routes, so look on the routers themselves.
    routes = [r for r in csv_routes.router.routes + import_routes.router.routes if isinstance(r, APIRoute)]
    route = next(r for r in routes if "POST" in r.methods and r.path_format == path.replace("/1/", "/{upload_id}/"))
    calls = [d.call for d in route.dependant.dependencies]
    assert concurrency.import_slot in calls, f"{path} is not limited"
    before = calls[: calls.index(concurrency.import_slot)]
    assert any(getattr(c, "__name__", "") == "check" for c in before), "the permission check must come first"


def test_the_limit_and_the_pool_behaviour_are_documented():
    """BR-58 asks for the pool-exhaustion behaviour to be documented, and an operator must find the setting."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "ENV_VARIABLES.md").read_text(encoding="utf-8")
    row = next((line for line in text.splitlines() if line.startswith("| `API_MAX_CONCURRENT_IMPORTS`")), "")
    assert row, "docs/ENV_VARIABLES.md must document API_MAX_CONCURRENT_IMPORTS"
    for needed in ("4", "503", "Retry-After", "0", "pool"):
        assert needed in row, f"the row should mention {needed!r}: {row}"
    pool_row = next(line for line in text.splitlines() if line.startswith("| `API_POOL_GETCONN_TIMEOUT`"))
    assert "503" in pool_row and "8" in pool_row, "the pool row should say what happens when the pool is exhausted"
