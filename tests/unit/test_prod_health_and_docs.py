"""#291 (OIT-006, BR-54): outside dev, the unauthenticated endpoints must not describe the system.

``/api/health`` is deliberately open so uptime probes work without the shared key (BUG-035). It also returned
the database name, the host and port, the PostgreSQL version and the uploads schema, and the interactive docs
(``/docs``, ``/redoc``, ``/openapi.json``) listed every route: a reconnaissance aid for anyone who can reach the
port. Asserted here:

  * with ``API_ENV`` anything but ``dev``, the health body is only ``status`` (``ok`` or ``degraded``);
  * with ``API_ENV=dev`` the health body is unchanged;
  * outside dev the docs routes are not served (404); in dev they are.

The health tests replace the database connection, so they need no PostgreSQL. The docs routes are fixed when
the app is created, so they are checked in a fresh process per environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from api import main
from api.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
DEV_KEYS = {"status", "database", "host", "postgres", "uploads_schema"}


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return ("PostgreSQL 16.4 on x86_64-pc-linux-gnu, compiled by gcc",)


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor()


class _BrokenConn(_Conn):
    def __enter__(self):
        raise RuntimeError("connection to server at 10.1.2.3, port 5432 failed: password authentication failed")


def health(monkeypatch, api_env: str, *, database_up: bool = True) -> dict:
    monkeypatch.setattr(settings, "API_ENV", api_env)
    monkeypatch.setattr(main.db, "Conn", _Conn if database_up else _BrokenConn)
    return main.health()


# -- /api/health ------------------------------------------------------------------------------------------------

def test_in_dev_the_health_body_keeps_its_details(monkeypatch):
    body = health(monkeypatch, "dev")
    assert set(body) == DEV_KEYS and body["status"] == "ok", body
    assert body["postgres"].startswith("PostgreSQL 16"), body


@pytest.mark.parametrize("api_env", ["prod", "production", "staging", "test"])
def test_outside_dev_the_health_body_is_only_the_status(monkeypatch, api_env):
    assert health(monkeypatch, api_env) == {"status": "ok"}


@pytest.mark.parametrize("api_env", ["prod", "staging"])
def test_outside_dev_a_failing_database_is_only_degraded(monkeypatch, api_env):
    assert health(monkeypatch, api_env, database_up=False) == {"status": "degraded"}


def test_in_dev_a_failing_database_still_says_why_in_general_terms(monkeypatch):
    body = health(monkeypatch, "dev", database_up=False)
    assert body["status"] == "degraded" and "unreachable" in body["error"], body
    assert "10.1.2.3" not in json.dumps(body), "the driver's message must never be returned"


def test_the_production_body_names_nothing_about_the_database(monkeypatch):
    text = json.dumps(health(monkeypatch, "prod"))
    for secret in (settings.PG_DATABASE, settings.PG_HOST, str(settings.PG_PORT), settings.UPLOADS_SCHEMA,
                   "PostgreSQL"):
        assert str(secret) not in text, f"{secret!r} is in {text}"


# -- /docs, /redoc, /openapi.json --------------------------------------------------------------------------------

def docs_statuses(api_env: str) -> dict[str, int]:
    """Status of each docs route in a fresh process that creates the app with this API_ENV."""
    code = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from api.main import app\n"
        "c = TestClient(app)\n"
        "print(json.dumps({p: c.get(p).status_code for p in ('/docs', '/redoc', '/openapi.json')}))\n"
    )
    env = {**os.environ, "API_ENV": api_env, "API_KEY": "k" * 24}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=180)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_in_dev_the_interactive_docs_are_served():
    assert docs_statuses("dev") == {"/docs": 200, "/redoc": 200, "/openapi.json": 200}


@pytest.mark.parametrize("api_env", ["prod", "staging"])
def test_outside_dev_the_docs_routes_are_not_served(api_env):
    assert docs_statuses(api_env) == {"/docs": 404, "/redoc": 404, "/openapi.json": 404}
