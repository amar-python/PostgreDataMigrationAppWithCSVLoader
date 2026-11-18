"""scripts/pg_login.py: save and check the PostgreSQL owner login for local development.

The point is that nothing has to ask for the password every time, without a wrong one ever being
saved: `save` tests the login first and writes nothing if the server refuses it, `check` says
which of "refused" and "not reachable" happened (the first needs a different password, the second
a running server), and the password is never printed.

The PowerShell side (scripts/start-api.ps1, scripts/dev-env.ps1) cannot run here, so the tests pin
what it depends on: the file format, the file name and the exit codes.

No database needed: psycopg2.connect is monkeypatched.
"""
import os
import re
from pathlib import Path

import psycopg2
import pytest

from scripts import pg_login

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
SECRET = "p4ss=w0rd with 'quotes' and =signs"  # '=' and spaces: the awkward cases for KEY=VALUE

REFUSED_MSG = ('connection to server at "localhost" (::1), port 5433 failed: '
               'FATAL:  password authentication failed for user "postgres"')
UNREACHABLE_MSG = ('connection to server at "localhost" (::1), port 5433 failed: Connection refused\n'
                   '\tIs the server running on that host and accepting TCP/IP connections?')


class _Conn:
    def close(self):
        pass


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    """No real home folder, no inherited PG* or password variables, and no real prompt."""
    monkeypatch.setattr(pg_login, "CREDENTIALS_DIR", tmp_path / ".te-migration")
    for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "TE_PG_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pg_login.getpass, "getpass", lambda *a, **k: pytest.fail("asked for a password"))


@pytest.fixture
def connects(monkeypatch):
    """psycopg2.connect succeeds and records what it was given."""
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return _Conn()

    monkeypatch.setattr(psycopg2, "connect", connect)
    return calls


def _fails(monkeypatch, message):
    def connect(**kwargs):
        raise psycopg2.OperationalError(message)

    monkeypatch.setattr(psycopg2, "connect", connect)


def _saved(tmp_path, env="dev"):
    return tmp_path / ".te-migration" / f"pg-{env}.env"


# ── save ──────────────────────────────────────────────────────────────────────────────────

def test_save_checks_the_login_then_writes_all_four_values(connects, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)

    assert pg_login.main(["save"]) == 0

    assert connects == [{"host": "localhost", "port": "5433", "user": "postgres", "password": SECRET,
                         "dbname": "postgres", "connect_timeout": 5}]
    assert pg_login.read_env_file(_saved(tmp_path)) == {
        "PGHOST": "localhost", "PGPORT": "5433", "PGUSER": "postgres", "PGPASSWORD": SECRET}
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err, "the password is never printed"
    assert "dev-env.ps1" in out.out, "it says how to load the login into a window"


@pytest.mark.skipif(os.name == "nt", reason="file modes are not meaningful on Windows")
def test_the_file_is_readable_by_the_current_user_only(connects, monkeypatch, tmp_path):
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)
    pg_login.main(["save"])
    assert _saved(tmp_path).stat().st_mode & 0o777 == 0o600


def test_a_refused_login_is_not_saved(monkeypatch, tmp_path, capsys):
    _fails(monkeypatch, REFUSED_MSG)
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)

    assert pg_login.main(["save"]) == 1

    assert not _saved(tmp_path).exists(), "a typo must never be saved"
    err = capsys.readouterr().err
    assert "refused the login" in err and "postgres@localhost:5433" in err
    assert "password authentication failed" in err, "the server's own reason is shown"
    assert "nothing was saved" in err
    assert SECRET not in err


def test_an_unreachable_server_is_not_saved_either_and_says_so(monkeypatch, tmp_path, capsys):
    _fails(monkeypatch, UNREACHABLE_MSG)
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)

    assert pg_login.main(["save"]) == 1

    assert not _saved(tmp_path).exists()
    assert "could not be reached" in capsys.readouterr().err


def test_no_check_saves_without_connecting(monkeypatch, tmp_path):
    monkeypatch.setattr(psycopg2, "connect", lambda **k: pytest.fail("tested the login"))
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)

    assert pg_login.main(["save", "--no-check"]) == 0
    assert pg_login.read_env_file(_saved(tmp_path))["PGPASSWORD"] == SECRET


def test_from_env_takes_the_whole_login_from_the_pg_variables_without_asking(connects, monkeypatch, tmp_path):
    monkeypatch.setenv("PGHOST", "db.example.test")
    monkeypatch.setenv("PGPORT", "6543")
    monkeypatch.setenv("PGUSER", "alice")
    monkeypatch.setenv("PGPASSWORD", SECRET)

    assert pg_login.main(["save", "--from-env"]) == 0

    assert pg_login.read_env_file(_saved(tmp_path)) == {
        "PGHOST": "db.example.test", "PGPORT": "6543", "PGUSER": "alice", "PGPASSWORD": SECRET}


def test_flags_override_the_variables_which_override_the_defaults(connects, monkeypatch):
    monkeypatch.setenv("PGHOST", "from-env")
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)

    pg_login.main(["save", "--host", "from-flag", "--port", "7000", "--user", "bob"])

    assert (connects[0]["host"], connects[0]["port"], connects[0]["user"]) == ("from-flag", "7000", "bob")


def test_the_password_prompt_names_who_it_is_for_and_is_the_only_source_left(connects, monkeypatch, tmp_path):
    asked = []

    def getpass(prompt):
        asked.append(prompt)
        return SECRET

    monkeypatch.setattr(pg_login.getpass, "getpass", getpass)

    assert pg_login.main(["save", "--user", "alice", "--host", "h", "--port", "1"]) == 0

    assert "alice@h:1" in asked[0] and "hidden" in asked[0]
    assert pg_login.read_env_file(_saved(tmp_path))["PGPASSWORD"] == SECRET


@pytest.mark.parametrize("password", ["", "line\nbreak"])
def test_an_empty_password_or_one_with_a_line_break_is_refused_before_anything_is_tried(
        connects, monkeypatch, tmp_path, password):
    monkeypatch.setattr(pg_login.getpass, "getpass", lambda *a, **k: password)

    assert pg_login.main(["save"]) == 2

    assert connects == [] and not _saved(tmp_path).exists()


def test_each_environment_has_its_own_file(connects, monkeypatch, tmp_path):
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)
    pg_login.main(["save", "--env", "test"])
    assert _saved(tmp_path, "test").exists() and not _saved(tmp_path, "dev").exists()


def test_an_unknown_environment_is_rejected():
    with pytest.raises(SystemExit) as info:
        pg_login.main(["save", "--env", "nope"])
    assert info.value.code == 2


# ── check ─────────────────────────────────────────────────────────────────────────────────

def test_check_exits_0_when_the_login_works(connects, monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", SECRET)

    assert pg_login.main(["check"]) == 0

    out = capsys.readouterr()
    assert "login works" in out.out and "postgres@localhost:5433" in out.out
    assert SECRET not in out.out + out.err
    assert connects[0]["password"] == SECRET


def test_check_exits_2_when_the_server_refuses_the_login(monkeypatch, capsys):
    _fails(monkeypatch, REFUSED_MSG)
    monkeypatch.setenv("PGPASSWORD", SECRET)

    assert pg_login.main(["check"]) == 2

    err = capsys.readouterr().err
    assert "refused the login" in err and "password authentication failed" in err
    assert SECRET not in err and "Traceback" not in err


def test_check_exits_3_when_the_server_cannot_be_reached(monkeypatch, capsys):
    _fails(monkeypatch, UNREACHABLE_MSG)

    assert pg_login.main(["check"]) == 3

    err = capsys.readouterr().err
    assert "Could not reach PostgreSQL at localhost:5433" in err and "running" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("message", [
    'connection to server at "localhost" (::1), port 5433 failed: FATAL:  role "ghost" does not exist',
    'connection to server at "localhost" (::1), port 5433 failed: FATAL:  database "x" does not exist',
    'connection to server at "h", port 5432 failed: FATAL:  no pg_hba.conf entry for host "1.2.3.4"',
])
def test_other_rejections_are_refusals_too(monkeypatch, message):
    _fails(monkeypatch, message)
    assert pg_login.main(["check"]) == 2


@pytest.mark.parametrize("message", [
    'connection to server at "db", port 5432 failed: FATAL:  the database system is starting up',
    'connection to server at "db", port 5432 failed: timeout expired',
])
def test_a_server_that_is_still_starting_or_slow_is_not_a_refusal(monkeypatch, message):
    _fails(monkeypatch, message)
    assert pg_login.main(["check"]) == 3


def test_check_uses_the_login_defaults_when_nothing_is_set(connects):
    pg_login.main(["check"])
    assert (connects[0]["host"], connects[0]["port"], connects[0]["user"]) == ("localhost", "5433", "postgres")


# ── where ─────────────────────────────────────────────────────────────────────────────────

def test_where_says_when_nothing_is_saved(capsys):
    assert pg_login.main(["where"]) == 0
    assert "No saved login for dev" in capsys.readouterr().out


def test_where_shows_the_path_and_what_it_holds_but_never_the_password(connects, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TE_PG_PASSWORD", SECRET)
    pg_login.main(["save"])
    capsys.readouterr()

    assert pg_login.main(["where"]) == 0

    out = capsys.readouterr().out
    assert str(_saved(tmp_path)) in out and "PGUSER=postgres" in out and "PGPORT=5433" in out
    assert SECRET not in out and "saved, not shown" in out


# ── the file format PowerShell reads ──────────────────────────────────────────────────────

def test_the_file_round_trips_a_password_with_equals_signs_spaces_and_quotes(tmp_path):
    path = tmp_path / "f.env"
    login = {"PGHOST": "h", "PGPORT": "5433", "PGUSER": "u", "PGPASSWORD": SECRET}

    pg_login.write_env_file(path, login)

    assert pg_login.read_env_file(path) == login


def test_the_file_is_read_the_way_the_powershell_scripts_read_it(tmp_path):
    """start-api.ps1 and dev-env.ps1 split each line on the FIRST '=' (`-split "=", 2`). A password
    containing '=' must survive that, and the lines must be exactly KEY=VALUE."""
    path = tmp_path / "f.env"
    login = {"PGHOST": "h", "PGPORT": "5433", "PGUSER": "u", "PGPASSWORD": SECRET}
    pg_login.write_env_file(path, login)

    powershell_view = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())

    assert powershell_view == login
    assert all(key.startswith("PG") for key in powershell_view), "the loaders only accept PG* keys"


def test_unknown_keys_comments_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "f.env"
    path.write_text("# a comment\n\nPGUSER=u\nOTHER=x\nnot a pair\nPGPASSWORD=a=b\n", encoding="utf-8")
    assert pg_login.read_env_file(path) == {"PGUSER": "u", "PGPASSWORD": "a=b"}


# ── the PowerShell side, pinned to this script (it cannot be run here) ────────────────────

START_API = ROOT / "scripts" / "start-api.ps1"
DEV_ENV = ROOT / "scripts" / "dev-env.ps1"


@pytest.mark.parametrize("script", [START_API, DEV_ENV], ids=lambda p: p.name)
def test_the_powershell_scripts_are_ascii_only(script):
    """Windows PowerShell 5.1 mis-parses non-ASCII text in a file without a BOM (BUG-021)."""
    text = script.read_bytes()
    bad = [i for i, b in enumerate(text) if b > 127]
    assert not bad, f"{script.name} has non-ASCII bytes at {bad[:5]}"


@pytest.mark.parametrize("script", [START_API, DEV_ENV], ids=lambda p: p.name)
def test_the_powershell_scripts_read_the_file_pg_login_writes(script):
    code = script.read_text(encoding="ascii")
    # The scripts build the path as "<profile>\.te-migration\pg-{0}.env" -f <env>; save writes
    # <home>/.te-migration/pg-<env>.env. Same folder, same file name, or they never meet.
    assert ".te-migration\\pg-{0}.env" in code
    assert pg_login.env_file_for("dev").name == "pg-{0}.env".format("dev")
    assert pg_login.env_file_for("dev").parent.name == ".te-migration"
    assert pg_login.__doc__ and "~/.te-migration/pg-<env>.env" in pg_login.__doc__


def test_dev_env_never_uses_exit_because_it_is_dot_sourced():
    """`exit` in a dot-sourced script closes the window it was sourced into."""
    code = "\n".join(line for line in DEV_ENV.read_text(encoding="ascii").splitlines()
                     if not line.lstrip().startswith("#"))
    assert not re.search(r"(?m)^\s*exit\b", code)
    assert re.search(r"(?m)^\s*return\b", code)


def test_start_api_acts_on_the_exit_codes_pg_login_check_documents():
    code = START_API.read_text(encoding="ascii")
    assert "pg_login.py" in code
    assert "$pgCode -eq 0" in code, "0: the login works, carry on"
    assert "$pgCode -ne 2" in code, "anything but 2 (not reachable) stops: asking again cannot help"
    assert "save --env $env:API_ENV --from-env" in code, "offers to save a typed login without typing it twice"
    doc = " ".join(pg_login.__doc__.split())
    assert "0 the login works, 2 the server refused it" in doc and "3 the server could not be reached" in doc
