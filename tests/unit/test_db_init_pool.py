"""init_pool / owner_connect: retry only transient connection failures (BUG-026), fail fast otherwise.

A wrong or missing password, a missing database, a ``pg_hba.conf`` rejection and the like cannot be
fixed by waiting, so ``init_pool`` must raise on the first attempt instead of backing off for ~4.5
minutes. A server that is still starting (BUG-026) must still be retried. The scripts turn the
resulting ``DatabaseConnectError`` into one message and exit status 1, not a traceback.

The migrations that run at startup (``bootstrap``) log in as the owner (PGUSER), a different login
from the pool's, so a wrong owner password must surface as the same short, named error, not
SQLAlchemy's long chained traceback (tests at the end).

No database needed. Most tests monkeypatch psycopg2's pool and ``time.sleep``; a few talk to a fake
PostgreSQL on loopback so that real libpq produces the message text the classifier has to read.
"""
import os
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.pool
import pytest
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlalchemy.exc import ProgrammingError

from api import db
from api.config import settings
from pydantic import SecretStr

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_PREFIX = 'connection to server at "localhost" (::1), port 5433 failed: '
_SECRET = "hunter2-sentinel"


def _server_sent(message, severity="FATAL"):
    """How libpq renders an error the server sent: ``SEVERITY:  message``."""
    return f"{_PREFIX}{severity}:  {message}"


# Real libpq message text, captured against PostgreSQL 16 with psycopg2 2.9.13. psycopg2 leaves
# exc.pgcode / exc.diag.sqlstate as None for connection-time errors, so the classifier reads this text.
PERMANENT = [
    _server_sent('password authentication failed for user "postgres"'),
    _server_sent('database "te_mgmt_dev" does not exist'),
    _server_sent('role "ghost" does not exist'),
    _server_sent('role "app" is not permitted to log in'),
    _server_sent('no pg_hba.conf entry for host "10.0.0.9", user "app", database "te_mgmt_dev", no encryption'),
    _server_sent('pg_hba.conf rejects connection for host "127.0.0.1", user "u", database "postgres", no encryption'),
    _server_sent('permission denied for database "te_mgmt_dev"\nDETAIL:  User does not have CONNECT privilege.'),
    _server_sent('Peer authentication failed for user "peeruser"'),
    _server_sent('database "lockeddb" is not currently accepting connections'),
    # Client-side, but waiting cannot supply a password or add SSL to the server.
    f"{_PREFIX}fe_sendauth: no password supplied",
    f"{_PREFIX}server does not support SSL, but SSL was required",
    # A rejection nobody has listed: still permanent, because the server answered with a FATAL.
    _server_sent("some rejection added in a future release"),
    # Another language, another severity word: the structure is what is recognised, not the words.
    _server_sent("Passwort-Authentifizierung für Benutzer »app« fehlgeschlagen"),
    _server_sent("парольная проверка подлинности пользователя «app» не прошла", severity="ВАЖНО"),
]

# The server is up (or the network is flapping) and waiting can help.
TRANSIENT = [
    f"{_PREFIX}Connection refused\n\tIs the server running on that host and accepting TCP/IP connections?",
    _server_sent("the database system is starting up"),
    _server_sent("the database system is shutting down"),
    _server_sent("the database system is not yet accepting connections\nDETAIL:  Consistent recovery state has not been yet reached."),
    _server_sent("the database system is in recovery mode"),
    _server_sent("sorry, too many clients already"),
    _server_sent("remaining connection slots are reserved for non-replication superuser connections"),
    _server_sent('too many connections for role "app"'),
    "could not translate host name \"db\" to address: Temporary failure in name resolution",
    f"{_PREFIX}timeout expired",
    f"{_PREFIX}Network is unreachable",
    f"{_PREFIX}server closed the connection unexpectedly\n\tThis probably means the server terminated abnormally",
    f"{_PREFIX}SSL SYSCALL error: EOF detected",
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

    with pytest.raises(db.DatabaseConnectError):
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


def test_transient_failure_keeps_attempt_count_and_backoff_cap(fake):
    """BUG-026 behaviour is unchanged: N attempts, delay capped at 10s."""
    err = psycopg2.OperationalError(TRANSIENT[0])
    fake.outcomes = [err]

    with pytest.raises(psycopg2.OperationalError):
        db.init_pool(max_attempts=12, base_delay=1.0)

    assert fake.attempts == 12
    assert fake.sleeps[:5] == [1.0, 2.0, 4.0, 8.0, 10.0]
    assert max(fake.sleeps) == 10.0


def test_giving_up_after_the_last_attempt_says_so_and_keeps_the_cause(fake):
    err = psycopg2.OperationalError(TRANSIENT[0])
    fake.outcomes = [err]

    with pytest.raises(db.DatabaseConnectError) as info:
        db.init_pool(max_attempts=4, base_delay=1.0)

    assert info.value.__cause__ is err
    assert "4 attempts" in str(info.value)
    assert "Connection refused" in str(info.value)


def test_database_connect_error_is_still_an_operational_error():
    """Callers (and BUG-026's 'fails loudly' contract) that catch OperationalError keep working."""
    assert issubclass(db.DatabaseConnectError, psycopg2.OperationalError)


def test_permanent_failure_message_names_user_host_port_and_env_vars(fake, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_USER", "")
    monkeypatch.setattr(settings, "PG_USER", "alice")
    monkeypatch.setattr(settings, "PG_HOST", "db.example.test")
    monkeypatch.setattr(settings, "PG_PORT", 6543)
    monkeypatch.setattr(settings, "PG_PASSWORD", SecretStr(_SECRET))
    fake.outcomes = [psycopg2.OperationalError(PERMANENT[0])]

    with pytest.raises(db.DatabaseConnectError) as info:
        db.init_pool()

    msg = str(info.value)
    assert "alice" in msg and "db.example.test" in msg and "6543" in msg
    assert "PGUSER" in msg and "PGPASSWORD" in msg
    assert "password authentication failed" in msg  # the server's own reason is kept
    assert "not reachable" not in msg
    assert _SECRET not in msg


def test_permanent_failure_message_names_the_runtime_role_when_one_is_configured(fake, monkeypatch):
    """The pool connects as APP_DB_USER when set, so that is the user to name, and the
    variables to check are APP_DB_USER / APP_DB_PASSWORD, not PGUSER / PGPASSWORD."""
    monkeypatch.setattr(settings, "PG_USER", "owner")
    monkeypatch.setattr(settings, "APP_DB_USER", "te_runtime")
    fake.outcomes = [psycopg2.OperationalError(PERMANENT[0])]

    with pytest.raises(db.DatabaseConnectError) as info:
        db.init_pool()

    msg = str(info.value)
    assert "te_runtime" in msg and "APP_DB_USER" in msg and "APP_DB_PASSWORD" in msg
    assert "owner" not in msg


# ── owner_connect: one connection as the owner, no retry ──────────────────────────────────

def test_owner_connect_turns_a_connection_failure_into_the_same_clear_error(monkeypatch):
    calls = []

    def refuse(**kwargs):
        calls.append(kwargs)
        raise psycopg2.OperationalError(PERMANENT[0])

    monkeypatch.setattr(psycopg2, "connect", refuse)
    monkeypatch.setattr(settings, "PG_USER", "owner")
    monkeypatch.setattr(settings, "APP_DB_USER", "te_runtime")  # irrelevant to an owner connection

    with pytest.raises(db.DatabaseConnectError) as info:
        with db.owner_connect():
            pytest.fail("no connection was made")

    msg = str(info.value)
    assert len(calls) == 1
    assert "owner" in msg and "PGUSER" in msg and "PGPASSWORD" in msg
    assert "te_runtime" not in msg


# ── run_cli: what the scripts use instead of a traceback ──────────────────────────────────

def test_run_cli_passes_the_exit_status_through():
    assert db.run_cli(lambda: 7) == 7


def test_run_cli_prints_a_connection_error_and_returns_1(capsys):
    def main():
        raise db.DatabaseConnectError("Could not connect to PostgreSQL at h:1 as u")

    assert db.run_cli(main) == 1

    out = capsys.readouterr()
    assert "Could not connect to PostgreSQL at h:1 as u" in out.err
    assert "Traceback" not in out.err and out.out == ""


def test_run_cli_does_not_hide_other_errors():
    def main():
        raise psycopg2.OperationalError("deadlock detected")

    with pytest.raises(psycopg2.OperationalError):
        db.run_cli(main)


# ── Real libpq against a fake server ──────────────────────────────────────────────────────

def _error_response(code, message, severity="FATAL"):
    fields = b"".join(tag.encode() + value.encode() + b"\0" for tag, value in
                      (("S", severity), ("V", "FATAL"), ("C", code), ("M", message))) + b"\0"
    return b"E" + struct.pack("!I", len(fields) + 4) + fields


class _FakePostgres(socketserver.ThreadingTCPServer):
    """Answers every connection's startup packet with one ErrorResponse, as a server that refuses it."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, reply: bytes):
        class Handler(socketserver.BaseRequestHandler):
            def handle(handler):
                self.connections += 1
                while True:
                    head = handler.request.recv(8)
                    if len(head) < 8:
                        return
                    length, code = struct.unpack("!II", head)
                    if code in (80877103, 80877104):  # SSLRequest / GSSENCRequest: say no, go on
                        handler.request.sendall(b"N")
                        continue
                    handler.request.recv(length - 8)  # the rest of the startup packet
                    handler.request.sendall(reply)
                    return

        super().__init__(("127.0.0.1", 0), Handler)
        self.connections = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self):
        return self.server_address[1]


@pytest.fixture
def fake_postgres():
    servers = []

    def start(code, message, severity="FATAL"):
        server = _FakePostgres(_error_response(code, message, severity))
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return sleeps


def _point_at(monkeypatch, server):
    monkeypatch.setattr(settings, "PG_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "PG_PORT", server.port)
    monkeypatch.setattr(settings, "PG_USER", "alice")
    monkeypatch.setattr(settings, "APP_DB_USER", "")
    monkeypatch.setattr(settings, "PG_PASSWORD", SecretStr(_SECRET))
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_getconn_executor", None)


@pytest.mark.parametrize("code, message, severity", [
    ("28P01", 'password authentication failed for user "alice"', "FATAL"),
    ("28000", "Passwort-Authentifizierung für Benutzer »alice« fehlgeschlagen", "FATAL"),
    ("28000", "парольная проверка подлинности пользователя «alice» не прошла", "ВАЖНО"),
])
def test_real_libpq_permanent_rejection_stops_after_one_connection(
        fake_postgres, no_sleep, monkeypatch, code, message, severity):
    server = fake_postgres(code, message, severity)
    _point_at(monkeypatch, server)

    with pytest.raises(db.DatabaseConnectError) as info:
        db.init_pool()

    assert server.connections == 1
    assert no_sleep == []
    assert "alice" in str(info.value) and str(server.port) in str(info.value)


def test_real_libpq_server_starting_up_is_retried(fake_postgres, no_sleep, monkeypatch):
    server = fake_postgres("57P03", "the database system is starting up")
    _point_at(monkeypatch, server)

    with pytest.raises(db.DatabaseConnectError):
        db.init_pool(max_attempts=3, base_delay=1.0)

    assert server.connections == 3


def test_script_with_a_refused_login_exits_1_at_once_without_a_traceback(fake_postgres, tmp_path):
    """The reported symptom: reset_password.py with a wrong PGPASSWORD looped until Ctrl+C."""
    server = fake_postgres("28P01", 'password authentication failed for user "alice"')
    env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(server.port), "PGUSER": "alice",
           "PGPASSWORD": _SECRET, "TE_NEW_PASSWORD": "a-long-enough-password-123", "APP_DB_USER": ""}
    script = Path(__file__).resolve().parents[2] / "scripts" / "reset_password.py"

    started = time.monotonic()
    done = subprocess.run([sys.executable, str(script), "--username", "admin"], env=env,
                          capture_output=True, text=True, timeout=60, cwd=tmp_path)

    assert time.monotonic() - started < 30  # not 30 attempts of backoff
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert f"127.0.0.1:{server.port} as alice" in done.stderr
    assert "PGUSER / PGPASSWORD" in done.stderr
    assert _SECRET not in done.stderr and server.connections == 1


# ── bootstrap(): the migrations' own login (the owner, PGUSER) ────────────────────────────

def _alembic_fails_with(monkeypatch, exc: Exception):
    """Make `alembic upgrade head` raise ``exc``, as env.py's engine.connect() would."""
    def boom(*args, **kwargs):
        raise exc
    monkeypatch.setattr("alembic.command.upgrade", boom)


def _wrapped(message: str) -> SQLAlchemyOperationalError:
    """What SQLAlchemy raises around psycopg2's error (its str() adds a 'Background on this error' line)."""
    return SQLAlchemyOperationalError("SELECT 1", {}, psycopg2.OperationalError(message))


@pytest.mark.parametrize("message", PERMANENT)
def test_bootstrap_login_refusal_raises_the_short_named_error(monkeypatch, message):
    _alembic_fails_with(monkeypatch, _wrapped(message))

    with pytest.raises(db.DatabaseConnectError) as info:
        db.bootstrap()

    assert not isinstance(info.value, SQLAlchemyOperationalError)
    assert info.value.__cause__ is None and info.value.__suppress_context__, \
        "the long SQLAlchemy chain must not be printed under it"
    assert "Background on this error" not in str(info.value), "SQLAlchemy's own footer is not repeated"


def test_bootstrap_login_refusal_names_the_owner_host_port_and_variables(monkeypatch):
    monkeypatch.setattr(settings, "PG_USER", "alice")
    monkeypatch.setattr(settings, "APP_DB_USER", "te_runtime")  # the pool's login, not the migrations'
    monkeypatch.setattr(settings, "PG_HOST", "db.example.test")
    monkeypatch.setattr(settings, "PG_PORT", 6543)
    monkeypatch.setattr(settings, "PG_PASSWORD", SecretStr(_SECRET))
    _alembic_fails_with(monkeypatch, _wrapped(PERMANENT[0]))

    with pytest.raises(db.DatabaseConnectError) as info:
        db.bootstrap()

    msg = str(info.value)
    assert "alice" in msg and "db.example.test" in msg and "6543" in msg
    assert "te_runtime" not in msg, "the migrations do not use the runtime role"
    assert "to run the database migrations" in msg, "it says why the owner is being used"
    assert "PGUSER" in msg and "PGPASSWORD" in msg
    assert "APP_DB_PASSWORD" not in msg
    assert "password authentication failed" in msg, "the server's own reason is kept"
    assert "not reachable" not in msg
    assert _SECRET not in msg


@pytest.mark.parametrize("message", TRANSIENT)
def test_bootstrap_leaves_a_transient_failure_alone(monkeypatch, message):
    err = _wrapped(message)
    _alembic_fails_with(monkeypatch, err)

    with pytest.raises(SQLAlchemyOperationalError) as info:
        db.bootstrap()

    assert info.value is err


def test_bootstrap_leaves_other_database_errors_alone(monkeypatch):
    err = ProgrammingError("CREATE TABLE x", {}, psycopg2.ProgrammingError("syntax error"))
    _alembic_fails_with(monkeypatch, err)

    with pytest.raises(ProgrammingError) as info:
        db.bootstrap()

    assert info.value is err


def test_a_script_that_calls_bootstrap_prints_the_refusal_and_exits_1(monkeypatch, capsys):
    """create_tenant_admin and the other scripts run db.bootstrap() under run_cli: the same short
    message must reach them (and a person) as plain text, not as a traceback."""
    monkeypatch.setattr(settings, "PG_USER", "alice")
    _alembic_fails_with(monkeypatch, _wrapped(PERMANENT[0]))

    assert db.run_cli(db.bootstrap) == 1

    err = capsys.readouterr().err
    assert "Could not connect to PostgreSQL" in err and "alice" in err
    assert "to run the database migrations" in err
    assert "Traceback" not in err
