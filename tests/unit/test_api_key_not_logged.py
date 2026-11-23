"""#292 (OIT-007, BR-55): the start-up log must not contain any part of API_KEY.

BUG-006 added a fingerprint to the start-up log so a script's key mismatch can be diagnosed: the first four
characters of the key plus its length. That is a partial secret in a log. The fingerprint is now a short
one-way hash prefix, which still tells two keys apart without containing any of the key.

Asserted by running the real ``lifespan`` with a known key and checking every substring of four or more
characters of that key against everything logged. No database is needed: the pool and bootstrap are replaced.
"""
from __future__ import annotations

import asyncio
import logging
import re

import pytest

from api import main
from api.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

KEY = "Zq9-known-test-key-QrStUvWx-31415"


def run_startup(monkeypatch, caplog, key: str) -> str:
    """Start the API's lifespan with ``key`` as API_KEY and return everything it logged."""
    monkeypatch.setattr(settings, "API_KEY", key)
    monkeypatch.setattr(settings, "API_ENV", "dev")
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


def test_no_part_of_the_key_is_in_the_startup_log(monkeypatch, caplog):
    logged = run_startup(monkeypatch, caplog, KEY)
    assert "API_KEY is set" in logged, "the test must have reached the branch that logs about the key"
    leaked = [KEY[i:i + n] for n in range(4, len(KEY) + 1) for i in range(len(KEY) - n + 1)
              if KEY[i:i + n] in logged]
    assert leaked == [], f"parts of the key are in the log: {leaked[:5]}"


def test_the_log_still_lets_you_tell_whether_two_keys_match(monkeypatch, caplog):
    logged = run_startup(monkeypatch, caplog, KEY)
    assert re.search(r"fingerprint: sha256:[0-9a-f]{8}\b", logged), logged
    assert f"length: {len(KEY)}" in logged, "a trailing space or newline in the key shows up as a wrong length"


@pytest.mark.parametrize("key", ["a", "ab", "abcd", KEY])
def test_any_key_length_works(monkeypatch, caplog, key):
    assert "API_KEY is set" in run_startup(monkeypatch, caplog, key)


def test_the_fingerprint_is_stable_short_and_tells_keys_apart():
    assert main.key_fingerprint(KEY) == main.key_fingerprint(KEY)
    assert main.key_fingerprint(KEY) != main.key_fingerprint(KEY + " ")
    assert re.fullmatch(r"[0-9a-f]{8}", main.key_fingerprint(KEY))
    assert KEY[:4] not in main.key_fingerprint(KEY)
