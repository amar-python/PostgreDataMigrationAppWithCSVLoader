"""pytest global configuration: environment-variable isolation between tests.

Mirrors the role of test-setup.ts in gstack: snapshots critical env vars
before each test and restores them after, preventing the common bug class
where one test sets CSV_FILE / PGPASSWORD / PATH and leaks that value into
an unrelated downstream test.
"""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests exercise the API directly via TestClient without an API key; bypass the
# require_api_key dependency for the whole test session rather than threading
# a header through every test's client.get/post/delete call.
from api.auth import require_api_key  # noqa: E402
from api.main import app  # noqa: E402

app.dependency_overrides[require_api_key] = lambda: None

# O-03: the rate-limit middleware is real for every TestClient request, and all
# tests share one bucket (TestClient always presents the same client identity).
# Left enabled, the write budget would start returning 429 partway through
# upload-heavy modules and fail tests for reasons unrelated to what they assert.
# Disable both budgets for the session — the same stance taken above for auth —
# and let tests that specifically exercise limiting set their own budgets.
from api.config import settings as _settings  # noqa: E402
from api.ratelimit import limiter as _limiter  # noqa: E402


_settings.RATE_LIMIT_READS_PER_MINUTE = 0
_settings.RATE_LIMIT_WRITES_PER_MINUTE = 0


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear limiter buckets so one test's request history cannot fail another."""
    _limiter.reset()
    yield
    _limiter.reset()


# ── Shared fixtures for tests that need the live API (#167) ───────────────────────────
# unittest.TestCase classes cannot take fixture arguments, so each fixture also attaches
# its value (`self.client`, `self.registry_cleanup`, ...) to the class or instance. Use
# them with @pytest.mark.usefixtures("live_api", "destructive_enabled") on the class.
# These fail, never skip, when PostgreSQL is not reachable, like the tests themselves.
from fastapi.testclient import TestClient  # noqa: E402
from psycopg2 import sql  # noqa: E402

from api.db import Conn  # noqa: E402

_START_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/PGPASSWORD/"
               "PGDATABASE). See scripts/start-api.ps1.")


@pytest.fixture(scope="class")
def destructive_enabled():
    """DELETE and overwrite are off unless API_ALLOW_DESTRUCTIVE is set; turn them on for one class."""
    original = _settings.allow_destructive
    _settings.allow_destructive = True
    yield
    _settings.allow_destructive = original


@pytest.fixture(scope="class")
def live_api(request):
    """The API started with its lifespan, so the database pool is up. ``self.client`` on a class."""
    ctx = TestClient(app)
    try:
        client = ctx.__enter__()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_START_HELP}") from None
    if request.cls is not None:
        request.cls.client = client
    yield client
    ctx.__exit__(None, None, None)


@pytest.fixture
def registry_cleanup(request, live_api, destructive_enabled):
    """File names the test registered; their csv_files rows (and tables) are deleted afterwards.

    Append names to the list: ``self.registry_cleanup.append(name)``.
    """
    names: list[str] = []
    if request.instance is not None:
        request.instance.registry_cleanup = names
    yield names
    for entry in live_api.get("/api/csv/files").json():
        if entry["file_name"] in names:
            live_api.delete(f"/api/csv/files/{entry['id']}")


@pytest.fixture
def te_org_cleanup(request):
    """Names of organisations the test inserted into the T&E schema; deleted afterwards.

    Append names to the list: ``self.te_org_cleanup.append(name)``.
    """
    names: list[str] = []
    if request.instance is not None:
        request.instance.te_org_cleanup = names
    yield names
    if names:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}.organisations WHERE name = ANY(%s)").format(
                sql.Identifier(_settings.TE_SCHEMA)), (names,))
            conn.commit()


# M7 (#111, BR-37): `pytest --block-egress` (or BLOCK_EGRESS=1) refuses any in-process connection that isn't
# to this machine, so a test run proves the application makes no outbound calls. See tests/egress_guard.py.
def pytest_addoption(parser):
    parser.addoption("--block-egress", action="store_true", default=False,
                     help="refuse network connections to anything but this machine, and fail if one is attempted")


def _egress_blocked(config) -> bool:
    return config.getoption("--block-egress") or os.environ.get("BLOCK_EGRESS") == "1"


def pytest_configure(config):
    if _egress_blocked(config):
        from tests import egress_guard
        egress_guard.check_local_database(_settings.PG_HOST)
        egress_guard.install()


def pytest_report_header(config):
    if _egress_blocked(config):
        return "egress: blocked (only this machine is reachable)"


def pytest_sessionfinish(session, exitstatus):
    if _egress_blocked(session.config):
        from tests import egress_guard
        egress_guard.uninstall()
        if egress_guard.attempts:
            print("\nEGRESS ATTEMPTED (blocked): " + "; ".join(sorted(set(egress_guard.attempts))))
            session.exitstatus = 1   # a swallowed EgressBlocked must still fail the run


# Folder -> marker (#167). The folder a test lives in is its category, so `-m system`,
# `-m "not accessibility"` and the Makefile targets agree with the layout without each
# test having to remember a decorator. `unit` stays explicit: it is what the free tier
# (and the Windows job) select on, and some folders mix it with finer markers.
_FOLDER_MARKERS = {
    "system": "system",
    "system_integration": "sit",
    "performance": "performance",
    "accessibility": "accessibility",
    "uat": "uat",
}


def pytest_collection_modifyitems(items):
    for item in items:
        for part in Path(str(item.fspath)).parts:
            marker = _FOLDER_MARKERS.get(part)
            if marker:
                item.add_marker(getattr(pytest.mark, marker))
                break


# Env vars tests are allowed to mutate; restored after every test.
_RESTORE_KEYS = (
    "CSV_FILE",
    "VALID_CSV",
    "SKIP_FILE",
    "TABLE_NAME",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PATH",
)


@pytest.fixture(autouse=True)
def _restore_env():
    baseline = {k: os.environ.get(k) for k in _RESTORE_KEYS}
    yield
    for k, v in baseline.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
