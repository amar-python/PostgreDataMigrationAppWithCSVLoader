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


# ── Test-group markers ────────────────────────────────────────────────────────
# Tests are grouped by folder (see tests/README.md). Every test inherits the
# marker of the folder it lives in, so `pytest -m uat` and `pytest tests/uat`
# select the same set.
_GROUP_MARKERS = {
    "unit": "unit",
    "system": "system",
    "system_integration": "sit",
    "performance": "performance",
    "accessibility": "accessibility",
    "uat": "uat",
}
_TESTS_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            rel = Path(str(item.fspath)).resolve().relative_to(_TESTS_ROOT)
        except ValueError:
            continue
        marker = _GROUP_MARKERS.get(rel.parts[0]) if len(rel.parts) > 1 else None
        if marker:
            item.add_marker(getattr(pytest.mark, marker))


# ── Live-database fixtures (system / SIT / performance / UAT) ─────────────────
_DB_HELP = (
    "Start PostgreSQL, set PGHOST/PGUSER/PGPASSWORD, point PGDATABASE at the "
    "provisioned dev database and deploy it:\n"
    "    bash scripts/provision_full_test_env.sh\n"
    "    export PGDATABASE=te_mgmt_dev"
)


@pytest.fixture(scope="module")
def live_api():
    """A TestClient with the FastAPI lifespan running (pool + bootstrap).

    Per the repository's no-skip policy an unreachable database FAILS with
    remediation text rather than skipping.
    """
    from fastapi.testclient import TestClient

    ctx = TestClient(app)
    try:
        client = ctx.__enter__()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "Could not start the API — database connection failed.\n"
            f"  {type(exc).__name__}: {str(exc).strip().splitlines()[0]}\n{_DB_HELP}",
            pytrace=False,
        )
    if client.get("/api/health").json().get("status") != "ok":
        ctx.__exit__(None, None, None)
        pytest.fail(f"API reports the database is unreachable.\n{_DB_HELP}", pytrace=False)
    yield client
    ctx.__exit__(None, None, None)


@pytest.fixture
def unique_tag(request):
    """Short tag unique to this test invocation — keeps content hashes from
    colliding with rows left behind by earlier runs."""
    import uuid

    return f"{request.node.name[:40]}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def registry_cleanup(live_api):
    """Collects uploaded file names and removes their registry rows (and, for
    dynamic uploads, their csv_<hash> tables) after the test, directly via SQL
    so cleanup works even while API_ALLOW_DESTRUCTIVE is off."""
    names: list[str] = []
    yield names
    if not names:
        return
    from psycopg2 import sql

    from api.config import settings
    from api.db import Conn

    schema = settings.UPLOADS_SCHEMA
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT id, table_name, mode FROM {}.csv_files WHERE file_name = ANY(%s)")
                .format(sql.Identifier(schema)),
                (names,),
            )
            for file_id, table_name, mode in cur.fetchall():
                if mode == "dynamic" and table_name.startswith("csv_"):
                    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table_name)))
                cur.execute(sql.SQL("DELETE FROM {}.csv_files WHERE id = %s")
                            .format(sql.Identifier(schema)), (file_id,))
        conn.commit()


@pytest.fixture
def destructive_enabled():
    """Temporarily enable DELETE /api/csv/files/{id} (API_ALLOW_DESTRUCTIVE)."""
    from api.config import settings

    original = settings.allow_destructive
    settings.allow_destructive = True
    yield
    settings.allow_destructive = original


@pytest.fixture
def te_org_cleanup(live_api):
    """Collects organisation names inserted into te_dev.organisations by a
    T&E-mode test and deletes them afterwards so seed data stays intact."""
    names: list[str] = []
    yield names
    if not names:
        return
    from psycopg2 import sql

    from api.config import settings
    from api.db import Conn

    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {}.organisations WHERE name = ANY(%s)")
                .format(sql.Identifier(settings.TE_SCHEMA)),
                (names,),
            )
        conn.commit()
