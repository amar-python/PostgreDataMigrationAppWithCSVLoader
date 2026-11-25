"""Start-up log about authentication (#292 OIT-007 / BR-55, #298 OIT-013).

#292: no part of a secret may reach the start-up log. The shared ``API_KEY`` was retired in #298, but an old
install may still set the variable. The API then warns that it is no longer used, and still logs no part of it.

#298: when local dev opts in to anonymous access, the start-up log says so loudly; without the opt-in it says
nothing about anonymous access.

Asserted by running the real ``lifespan``. No database is needed: the pool and bootstrap are replaced.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from api import main
from api.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

KEY = "Zq9-known-test-key-QrStUvWx-31415"


def run_startup(monkeypatch, caplog, *, key: str | None = None, anonymous: bool = False) -> str:
    """Start the API's lifespan and return everything it logged."""
    if key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", key)
    monkeypatch.setattr(settings, "API_ENV", "dev")
    monkeypatch.setattr(settings, "API_ALLOW_ANONYMOUS", anonymous)
    for name in ("init_pool", "bootstrap", "close_pool"):
        monkeypatch.setattr(main.db, name, lambda *a, **k: None)
    monkeypatch.setattr(main.oidc, "check_config", lambda: None)
    monkeypatch.setattr(main.policy, "check_config", lambda *a, **k: None)

    async def run() -> None:
        async with main.lifespan(main.app):
            pass

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    return "\n".join(record.getMessage() for record in caplog.records)


def test_a_leftover_key_is_reported_as_unused(monkeypatch, caplog):
    logged = run_startup(monkeypatch, caplog, key=KEY)
    assert "API_KEY is set but no longer used" in logged, logged


def test_no_part_of_a_leftover_key_is_in_the_startup_log(monkeypatch, caplog):
    logged = run_startup(monkeypatch, caplog, key=KEY)
    leaked = [KEY[i:i + n] for n in range(4, len(KEY) + 1) for i in range(len(KEY) - n + 1)
              if KEY[i:i + n] in logged]
    assert leaked == [], f"parts of the key are in the log: {leaked[:5]}"


def test_no_key_no_key_message(monkeypatch, caplog):
    assert "API_KEY" not in run_startup(monkeypatch, caplog)


def test_anonymous_access_is_announced_loudly(monkeypatch, caplog):
    run_startup(monkeypatch, caplog, anonymous=True)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "ANONYMOUS ACCESS IS ON" in r.getMessage()]
    assert warnings, "the opt-in must produce a WARNING at start-up"


def test_no_anonymous_warning_without_the_opt_in(monkeypatch, caplog):
    assert "ANONYMOUS" not in run_startup(monkeypatch, caplog)
