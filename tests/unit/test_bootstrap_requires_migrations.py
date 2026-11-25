"""#317 (OIT-028, BR-35): outside dev, the API must not start without its migrations.

``bootstrap()`` brings the schema to head through Alembic. If ``alembic.ini`` was missing (a packaging mistake) it fell back
to a hand-written ``CREATE TABLE IF NOT EXISTS`` schema with a warning. That schema has no hash chain and no append-only
triggers, so a deployment with a packaging slip would run, silently, without the audit protections. Asserted here:

  * with ``API_ENV`` anything but ``dev`` and ``alembic.ini`` missing, ``bootstrap()`` raises and the fallback is not
    used, and so does the real start-up (``lifespan``): the API does not come up;
  * in dev the fallback still works, but is reported at ERROR level, not as a warning;
  * the API image does ship ``alembic.ini``, ``alembic/`` and ``alembic_te/`` (the packaging this guards against).

No database is needed: the fallback and the pool are replaced.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from api import db, main
from api.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
MISSING = Path("/nonexistent/place/alembic.ini")


@pytest.fixture
def fallback_calls(monkeypatch):
    """alembic.ini is missing; the hand-written fallback is replaced by a recorder."""
    calls: list[str] = []
    monkeypatch.setattr(db, "alembic_ini_path", lambda: MISSING)
    monkeypatch.setattr(db, "_bootstrap_fallback_schema", lambda: calls.append("fallback"))
    return calls


@pytest.mark.parametrize("api_env", ["prod", "production", "staging", "test"])
def test_outside_dev_a_missing_alembic_ini_stops_bootstrap(monkeypatch, fallback_calls, api_env):
    monkeypatch.setattr(settings, "API_ENV", api_env)
    with pytest.raises(RuntimeError) as raised:
        db.bootstrap()
    message = str(raised.value)
    assert "alembic.ini" in message and str(MISSING) in message and "refusing to start" in message, message
    assert fallback_calls == [], "the schema with no audit triggers must not be created"


def test_outside_dev_the_api_does_not_start_without_alembic_ini(monkeypatch, fallback_calls):
    """The acceptance criterion: with alembic.ini absent and API_ENV=prod, start-up fails."""
    monkeypatch.setattr(settings, "API_ENV", "prod")
    monkeypatch.setattr(settings, "API_ALLOW_ANONYMOUS", False)  # the suite opts in; not allowed outside dev (#298)
    monkeypatch.setattr(main.oidc, "check_config", lambda: None)
    monkeypatch.setattr(main.policy, "check_config", lambda *a, **k: None)
    monkeypatch.setattr(main.db, "init_pool", lambda: None)
    monkeypatch.setattr(main.db, "close_pool", lambda: None)

    async def start() -> None:
        async with main.lifespan(main.app):
            pytest.fail("the API must not have come up")

    with pytest.raises(RuntimeError, match="alembic.ini"):
        asyncio.run(start())
    assert fallback_calls == []


def test_in_dev_the_fallback_still_runs_but_is_reported_as_an_error(monkeypatch, caplog, fallback_calls):
    monkeypatch.setattr(settings, "API_ENV", "dev")
    with caplog.at_level(logging.DEBUG, logger=db.logger.name):
        db.bootstrap()
    assert fallback_calls == ["fallback"]
    levels = {r.levelno for r in caplog.records if "alembic.ini" in r.getMessage()}
    assert levels == {logging.ERROR}, f"the missing file must be an error in the log, not a warning: {levels}"


def test_the_api_image_ships_the_migrations():
    dockerfile = (ROOT / "container" / "api.Dockerfile").read_text(encoding="utf-8")
    copied = [line.split()[1].rstrip("/") for line in dockerfile.splitlines() if line.startswith("COPY ")]
    for needed in ("alembic.ini", "alembic", "alembic_te"):
        assert needed in copied, f"container/api.Dockerfile must COPY {needed}"
