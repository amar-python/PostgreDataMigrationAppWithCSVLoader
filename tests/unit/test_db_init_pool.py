"""init_pool: retry only transient connection failures (BUG-026), fail fast otherwise.

A wrong password / missing database / no pg_hba.conf entry cannot be fixed by
waiting, so init_pool must raise on the first attempt instead of backing off for
~4.5 minutes. A server that is still starting (BUG-026) must still be retried.

No database needed: psycopg2's pool and time.sleep are monkeypatched.
"""
import time

import psycopg2
import psycopg2.pool
import pytest

from api import db
from api.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# Real libpq message text (psycopg2 leaves exc.pgcode = None for connection-time
# errors, so init_pool classifies on this text).
PERMANENT = [
    'connection to server at "localhost" (::1), port 5433 failed: '
    'FATAL:  password authentication failed for user "postgres"',
    'connection to server at "localhost" (::1), port 5433 failed: '
    'FATAL:  database "te_mgmt_dev" does not exist',
    'connection to server at "10.0.0.5", port 5432 failed: FATAL:  no pg_hba.conf entry for '
    'host "10.0.0.9", user "app", database "te_mgmt_dev", no encryption',
    'connection to server at "localhost" (::1), port 5433 failed: '
    'FATAL:  role "ghost" does not exist',
    'connection to server at "localhost" (::1), port 5433 failed: '
    'FATAL:  role "app" is not permitted to log in',
]

TRANSIENT = [
    'connection to server at "localhost" (::1), port 5433 failed: Connection refused\n'
    '\tIs the server running on that host and accepting TCP/IP connections?',
    'connection to server at "db" (10.0.0.5), port 5432 failed: FATAL:  '
    'the database system is starting up',
    'connection to server at "db" (10.0.0.5), port 5432 failed: FATAL:  '
    'the database system is shutting down',
    'could not translate host name "db" to address: Temporary failure in name resolution',
    'connection to server at "db" (10.0.0.5), port 5432 failed: timeout expired',
]


class _Fake:
    """Scripted stand-in for ThreadedConnectionPool; the last outcome repeats."""

    def __init__(self):
        self.outcomes: list = []
        self.attempts = 0
        self.sleeps: list[float] = []

    def __call__(self, *args, **kwargs):
        self.attempts += 1
        out = self.outcomes[min(self.attempts, len(self.outcomes)) - 1]
        if isinstance(out, Exception):
            raise out
        return self

    def closeall(self):  # db.close_pool() calls this on the returned "pool"
        pass


@pytest.fixture
def fake(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", f)
    monkeypatch.setattr(time, "sleep", f.sleeps.append)
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_getconn_executor", None)
    yield f
    db.close_pool()  # shuts down the executor init_pool creates on success


@pytest.mark.parametrize("message", PERMANENT)
def test_permanent_failure_raises_on_first_attempt_without_sleeping(fake, message):
    fake.outcomes = [psycopg2.OperationalError(message)]

    with pytest.raises(psycopg2.OperationalError):
        db.init_pool()

    assert fake.attempts == 1
    assert fake.sleeps == []


@pytest.mark.parametrize("message", TRANSIENT)
def test_transient_failure_is_retried_until_it_succeeds(fake, message):
    """BUG-026: server not ready yet -> keep trying, then connect."""
    err = psycopg2.OperationalError(message)
    fake.outcomes = [err, err, "ok"]

    db.init_pool()

    assert fake.attempts == 3
    assert fake.sleeps == [1.0, 2.0]
    assert db._pool is fake


def test_transient_failure_keeps_attempt_count_backoff_cap_and_final_error(fake):
    """BUG-026 behaviour is unchanged: N attempts, delay capped at 10s, last error re-raised."""
    err = psycopg2.OperationalError(TRANSIENT[0])
    fake.outcomes = [err]

    with pytest.raises(psycopg2.OperationalError) as info:
        db.init_pool(max_attempts=12, base_delay=1.0)

    assert info.value is err
    assert fake.attempts == 12
    assert fake.sleeps[:5] == [1.0, 2.0, 4.0, 8.0, 10.0]
    assert max(fake.sleeps) == 10.0


def test_permanent_failure_message_names_user_host_port_and_env_vars(fake, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_USER", "")
    monkeypatch.setattr(settings, "PG_USER", "alice")
    monkeypatch.setattr(settings, "PG_HOST", "db.example.test")
    monkeypatch.setattr(settings, "PG_PORT", 6543)
    monkeypatch.setattr(settings, "PG_PASSWORD", "hunter2-sentinel")
    fake.outcomes = [psycopg2.OperationalError(PERMANENT[0])]

    with pytest.raises(psycopg2.OperationalError) as info:
        db.init_pool()

    msg = str(info.value)
    assert "alice" in msg and "db.example.test" in msg and "6543" in msg
    assert "PGUSER" in msg and "PGPASSWORD" in msg
    assert "password authentication failed" in msg  # the server's own reason is kept
    assert "not reachable" not in msg
    assert "hunter2-sentinel" not in msg


def test_permanent_failure_message_names_the_runtime_role_when_one_is_configured(fake, monkeypatch):
    """The pool connects as APP_DB_USER when set, so that is the user to name, and the
    variables to check are APP_DB_USER / APP_DB_PASSWORD, not PGUSER / PGPASSWORD."""
    monkeypatch.setattr(settings, "PG_USER", "owner")
    monkeypatch.setattr(settings, "APP_DB_USER", "te_runtime")
    fake.outcomes = [psycopg2.OperationalError(PERMANENT[0])]

    with pytest.raises(psycopg2.OperationalError) as info:
        db.init_pool()

    msg = str(info.value)
    assert "te_runtime" in msg and "APP_DB_USER" in msg and "APP_DB_PASSWORD" in msg
    assert "owner" not in msg
