"""#331: the API's settings are validated when it starts, and the reference doc matches them.

  - A bad value stops start-up with a message that names the variable, what it holds and what was expected, and lists
    every bad variable at once. The message never holds a password.
  - Ranges and allowed values are checked; values the API read before #331 still read the same way.
  - docs/ENV_VARIABLES.md lists every setting with the default the code uses.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from api.config import API_ENVS, ConfigError, Settings

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "ENV_VARIABLES.md"
SECRET = "Pa55-do-not-print-" + "x7Q"  # built from two pieces, so a secret scan never sees it whole


def _error(env: dict[str, str]) -> str:
    with pytest.raises(ConfigError) as caught:
        Settings.from_env(env)
    return str(caught.value)


# ── Defaults and the values that worked before #331 ─────────────────────────────────────────────────────────────

def test_an_empty_environment_gives_the_documented_defaults():
    s = Settings.from_env({})
    assert (s.PG_HOST, s.PG_PORT, s.PG_USER, s.PG_DATABASE) == ("localhost", 5432, "postgres", "te_mgmt_dev")
    assert s.PG_PASSWORD.get_secret_value() == "" and s.APP_DB_PASSWORD.get_secret_value() == ""
    assert (s.API_ENV, s.API_ALLOW_ANONYMOUS, s.allow_destructive, s.REQUIRE_TYPE_CONFIRMATION) == ("dev", False, False, False)
    assert s.CORS_ORIGINS == ["http://localhost:8080", "http://localhost:5173", "http://localhost:3000"]
    assert (s.MAX_ROWS, s.MAX_UPLOAD_BYTES, s.POOL_GETCONN_TIMEOUT) == (100000, 50 * 1024 * 1024, 5.0)


def test_values_are_read_from_their_environment_variables():
    s = Settings.from_env({"PGPORT": "6543", "CSV_UPLOADS_SCHEMA": "up", "API_MAX_ROWS": "10",
                           "API_POOL_GETCONN_TIMEOUT": "0.5", "CORS_ORIGINS": "https://a.example,https://b.example",
                           "API_ENV": " Prod ", "DATA_CLASSIFICATION": " OFFICIAL ", "PGPASSWORD": SECRET})
    assert (s.PG_PORT, s.UPLOADS_SCHEMA, s.MAX_ROWS, s.POOL_GETCONN_TIMEOUT) == (6543, "up", 10, 0.5)
    assert s.CORS_ORIGINS == ["https://a.example", "https://b.example"]
    assert (s.API_ENV, s.DATA_CLASSIFICATION) == ("prod", "OFFICIAL")  # stripped (and lower-cased) as before
    assert s.PG_PASSWORD.get_secret_value() == SECRET


@pytest.mark.parametrize("value, expected", [("1", True), ("true", True), ("YES", True),
                                             ("", False), ("0", False), ("false", False), ("No", False)])
def test_on_off_values_read_as_before(value, expected):
    for name, attr in (("API_ALLOW_DESTRUCTIVE", "allow_destructive"), ("API_ALLOW_ANONYMOUS", "API_ALLOW_ANONYMOUS"),
                       ("API_REQUIRE_TYPE_CONFIRMATION", "REQUIRE_TYPE_CONFIRMATION")):
        assert getattr(Settings.from_env({name: value}), attr) is expected, name


@pytest.mark.parametrize("value", API_ENVS)
def test_every_deployment_name_is_accepted(value):
    assert Settings.from_env({"API_ENV": value}).API_ENV == value


def test_zero_still_turns_off_the_limits_documented_as_off_at_zero():
    s = Settings.from_env({"SESSION_IDLE_MINUTES": "0", "API_RATE_LIMIT_READS": "0", "API_RATE_LIMIT_WRITES": "0",
                           "API_MAX_CONCURRENT_IMPORTS": "0", "SESSION_PURGE_GRACE_DAYS": "0"})
    assert (s.SESSION_IDLE_MINUTES, s.RATE_LIMIT_READS_PER_MINUTE, s.MAX_CONCURRENT_IMPORTS) == (0, 0, 0)


# ── Bad values ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_bad_value_names_the_variable_its_value_and_the_expected_format():
    msg = _error({"PGPORT": "abc"})
    assert "PGPORT='abc'" in msg and "valid integer" in msg


@pytest.mark.parametrize("name, value, expected", [
    ("PGPORT", "0", "greater than or equal to 1"),
    ("PGPORT", "70000", "less than or equal to 65535"),
    ("SESSION_TTL_HOURS", "-1", "greater than or equal to 1"),
    ("SESSION_IDLE_MINUTES", "-5", "greater than or equal to 0"),
    ("LOGIN_MAX_FAILURES", "0", "greater than or equal to 1"),
    ("LOGIN_LOCKOUT_MINUTES", "0", "greater than or equal to 1"),
    ("API_MAX_ROWS", "0", "greater than or equal to 1"),
    ("MAX_UPLOAD_BYTES", "0", "greater than or equal to 1"),
    ("API_POOL_GETCONN_TIMEOUT", "0", "greater than 0"),
    ("API_POOL_GETCONN_TIMEOUT", "soon", "valid number"),
    ("API_RATE_LIMIT_WRITES", "-1", "greater than or equal to 0"),
    ("API_ENV", "production", "dev, test, staging, prod"),
    # Before #331 these silently meant "off"; now they are refused instead of guessed at.
    ("API_ALLOW_DESTRUCTIVE", "on", "expected one of 1, true, yes"),
    ("API_ALLOW_ANONYMOUS", "enabled", "expected one of 1, true, yes"),
    ("API_REQUIRE_TYPE_CONFIRMATION", " true", "expected one of 1, true, yes"),
])
def test_out_of_range_and_unknown_values_are_refused(name, value, expected):
    msg = _error({name: value})
    assert f"{name}={value!r}" in msg and expected in msg, msg


def test_every_bad_variable_is_reported_at_once():
    msg = _error({"PGPORT": "x", "API_ENV": "nope", "SESSION_TTL_HOURS": "0", "PGHOST": "fine"})
    assert msg.startswith("Invalid configuration: 3 environment variables cannot be used.")
    assert all(n in msg for n in ("PGPORT=", "API_ENV=", "SESSION_TTL_HOURS="))
    assert "PGHOST" not in msg


def test_a_password_is_never_printed():
    s = Settings.from_env({"PGPASSWORD": SECRET, "APP_DB_PASSWORD": SECRET})
    assert SECRET not in repr(s) and SECRET not in str(s) and SECRET not in s.model_dump_json()
    # Even when the error is in the password itself or next to it: the message hides its value.
    for env in ({"PGPASSWORD": SECRET, "PGPORT": "bad"}, {"APP_DB_PASSWORD": SECRET, "API_ENV": "bad"}):
        assert SECRET not in _error(env)
    with pytest.raises(ConfigError) as caught:
        Settings.from_env({"PGPASSWORD": 12345})  # not a string, so the password itself is the bad value
    assert "PGPASSWORD=(value hidden)" in str(caught.value) and "12345" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__  # pydantic's own error is not chained


def test_the_api_refuses_to_start_with_a_named_error():
    """The real start-up path: importing the app with a bad value fails with ConfigError, not a bare ValueError."""
    env = {**os.environ, "PGPORT": "abc", "PGPASSWORD": SECRET}
    res = subprocess.run([sys.executable, "-c", "import api.main"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode != 0
    assert "api.config.ConfigError: Invalid configuration" in res.stderr and "PGPORT='abc'" in res.stderr
    assert SECRET not in res.stderr + res.stdout


def test_settings_still_accept_assignment():
    """api/tenancy.py points UPLOADS_SCHEMA at a tenant while it migrates; tests patch attributes."""
    s = Settings.from_env({})
    s.UPLOADS_SCHEMA = "tenant_x"
    assert s.UPLOADS_SCHEMA == "tenant_x"
    s.PG_PASSWORD = SecretStr(SECRET)
    assert s.PG_PASSWORD.get_secret_value() == SECRET


# ── docs/ENV_VARIABLES.md ───────────────────────────────────────────────────────────────────────────────────────

def _documented_defaults() -> dict[str, str]:
    """``{VARIABLE: first cell after the name}`` for every table row that starts with a `VARIABLE`."""
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|\s*([^|]*)\|", line)
        if m:
            rows.setdefault(m.group(1), m.group(2).strip())
    return rows


def _as_documented(default: object) -> set[str]:
    if isinstance(default, SecretStr):
        default = default.get_secret_value()
    if default is False:
        return {"`false`", "_(empty)_"}
    if isinstance(default, list):
        default = ",".join(default)
    return {"_(empty)_"} if default == "" else {f"`{default}`"}


def test_the_doc_lists_every_setting_with_its_default():
    documented = _documented_defaults()
    wrong = []
    for name, attr in Settings.env_names().items():
        if name not in documented:
            wrong.append(f"{name}: missing")
            continue
        field = Settings.model_fields[attr]
        default = field.get_default(call_default_factory=True)
        cell = documented[name]
        first_value = re.match(r"(`[^`]*`|_\(empty\)_)", cell)
        if not first_value or first_value.group(1) not in _as_documented(default):
            wrong.append(f"{name}: documented {cell!r}, code default {sorted(_as_documented(default))}")
    assert not wrong, "docs/ENV_VARIABLES.md disagrees with api/config.py:\n  " + "\n  ".join(wrong)
