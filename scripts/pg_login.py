"""Save and check the PostgreSQL owner login for local development (so nothing has to ask for it).

    python scripts/pg_login.py save [--env dev]     prompt for the password once, check it, save it
    python scripts/pg_login.py check                check the login in the current PG* variables
    python scripts/pg_login.py where [--env dev]    say where the saved file is, and what it holds

The login is saved to ~/.te-migration/pg-<env>.env, next to the API's runtime-role file
(app-db-<env>.env), in the same KEY=VALUE form. It is created with mode 0600 where the OS has
modes (Linux, macOS); on Windows it relies on the profile folder's default permissions. It is
plain text, like that file: fine for a development database that only this computer can reach,
not for anything else. scripts/start-api.ps1 loads it, and `. .\\scripts\\dev-env.ps1`
loads it into a PowerShell window for the other scripts (reset_password.py and so on).

`save` checks the login first and writes nothing if it is refused, so a typo is never saved.
`check` exit status: 0 the login works, 2 the server refused it (waiting will not help: a wrong
password, an unknown role, no pg_hba.conf entry), 3 the server could not be reached.
Neither command ever prints the password.

Both look for the server before they use a password. If PostgreSQL is not accepting connections
there is nothing for a password to be tested against, so `save` does not ask for one and `check`
does not try one. `check --server-only` does just that first step (exit 0 reachable, 3 not), which
is what scripts/start-api.ps1 runs before it asks for a password.
"""

from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402  (its classifier tells a refusal from a server that is not up)

ENVIRONMENTS = ("dev", "test", "staging", "prod")
CREDENTIALS_DIR = Path.home() / ".te-migration"
KEYS = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD")
# What start-api.ps1 uses when nothing else is set: the PostgreSQL 18 dev instance on 5433.
DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USER = "localhost", "5433", "postgres"

OK, REFUSED, UNREACHABLE = "ok", "refused", "unreachable"


def env_file_for(env: str) -> Path:
    return CREDENTIALS_DIR / f"pg-{env}.env"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, split on the first '=' (the same rule start-api.ps1 uses). Only PG* keys."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key in KEYS:
            values[key] = value
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Create the file with mode 0600 (applied on Linux and macOS; Windows ignores it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for key in KEYS:
            f.write(f"{key}={values[key]}\n")


def server_available(host: str, port: str, timeout: int = 5) -> tuple[bool, str]:
    """(reachable, a one-line reason): does anything accept a connection on host:port?

    Sends no credentials and no data, so it can run before anyone is asked for a password. The
    login is a separate question, answered by try_login. A host that is a directory (a Unix-socket
    path) is not probed here; try_login says whether that connects."""
    if host.startswith("/"):
        return True, ""
    try:
        socket.create_connection((host, int(port)), timeout=timeout).close()
    except ValueError:
        return False, f"the port {port!r} is not a number"
    except OSError as exc:
        return False, f"nothing accepted a connection on {host}:{port} ({exc})"
    return True, ""


def try_login(host: str, port: str, user: str, password: str, timeout: int = 5) -> tuple[str, str]:
    """(OK | REFUSED | UNREACHABLE, a one-line reason). Connects to the always-present `postgres`
    database, so only the credentials are tested, not whether a particular database exists."""
    try:
        psycopg2.connect(host=host, port=port, user=user, password=password,
                         dbname="postgres", connect_timeout=timeout).close()
    except psycopg2.OperationalError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        return (REFUSED if db._is_permanent(exc) else UNREACHABLE), reason
    return OK, ""


def _login_from_env() -> tuple[str, str, str, str]:
    return (os.environ.get("PGHOST") or DEFAULT_HOST, os.environ.get("PGPORT") or DEFAULT_PORT,
            os.environ.get("PGUSER") or DEFAULT_USER, os.environ.get("PGPASSWORD", ""))


def _not_reachable(host: str, port: str, reason: str) -> int:
    print(f"Could not reach PostgreSQL at {host}:{port}.\n  {reason}\n"
          "Check that the server is running on that host and port.", file=sys.stderr)
    return 3


def cmd_check(args) -> int:
    host, port, user, password = _login_from_env()
    up, why = server_available(host, port)          # first: is anything there to log in to?
    if not up:
        return _not_reachable(host, port, why)
    if args.server_only:
        print(f"PostgreSQL is accepting connections at {host}:{port}.")
        return 0
    status, reason = try_login(host, port, user, password)
    who = f"{user}@{host}:{port}"
    if status == OK:
        print(f"PostgreSQL login works ({who}).")
        return 0
    if status == REFUSED:
        print(f"PostgreSQL refused the login for {who}.\n  {reason}", file=sys.stderr)
        return 2
    return _not_reachable(host, port, reason)       # it went away, or is still starting up


def cmd_save(args) -> int:
    host = args.host or os.environ.get("PGHOST") or DEFAULT_HOST
    port = str(args.port or os.environ.get("PGPORT") or DEFAULT_PORT)
    user = args.user or os.environ.get("PGUSER") or DEFAULT_USER
    if not args.no_check:
        # Before asking for a password: with no server there is nothing to test it against.
        up, why = server_available(host, port)
        if not up:
            print(f"PostgreSQL could not be reached at {host}:{port}, so nothing was saved and no "
                  f"password was asked for.\n  {why}\n"
                  "Check that the server is running on that host and port, then run this again.",
                  file=sys.stderr)
            return 1
    if args.from_env:
        password = os.environ.get("PGPASSWORD", "")
    else:
        password = os.environ.get("TE_PG_PASSWORD") or getpass.getpass(
            f"Password for {user}@{host}:{port} (input hidden): ")
    if not password:
        print("No password given; nothing was saved.", file=sys.stderr)
        return 2
    if "\n" in password or "\r" in password:
        print("The password cannot contain a line break; nothing was saved.", file=sys.stderr)
        return 2
    if not args.no_check:
        status, reason = try_login(host, port, user, password)
        if status != OK:
            what = "refused the login" if status == REFUSED else "could not be reached"
            print(f"PostgreSQL {what} for {user}@{host}:{port}, so nothing was saved.\n  {reason}",
                  file=sys.stderr)
            return 1
    path = env_file_for(args.env)
    write_env_file(path, {"PGHOST": host, "PGPORT": port, "PGUSER": user, "PGPASSWORD": password})
    print(f"Saved the {args.env} login for {user}@{host}:{port} to {path}.\n"
          "start-api.ps1 will use it. For the other scripts, in a PowerShell window run:  "
          ". .\\scripts\\dev-env.ps1")
    return 0


def cmd_where(args) -> int:
    path = env_file_for(args.env)
    if not path.exists():
        print(f"No saved login for {args.env}. Save one with: python scripts/pg_login.py save --env {args.env}")
        return 0
    held = read_env_file(path)
    shown = {k: v for k, v in held.items() if k != "PGPASSWORD"}
    print(f"{path}\n  holds: " + ", ".join(f"{k}={v}" for k, v in shown.items())
          + (", PGPASSWORD=(saved, not shown)" if "PGPASSWORD" in held else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("save", help="check a login and save it for this environment")
    p.add_argument("--env", choices=ENVIRONMENTS, default="dev")
    p.add_argument("--host")
    p.add_argument("--port")
    p.add_argument("--user")
    p.add_argument("--from-env", action="store_true",
                   help="take the login from PGHOST / PGPORT / PGUSER / PGPASSWORD instead of asking")
    p.add_argument("--no-check", action="store_true", help="save without testing the login first")
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("check", help="test the login in the current PG* variables")
    p.add_argument("--server-only", action="store_true",
                   help="only check that PostgreSQL is accepting connections; use no password")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("where", help="say where the saved login is")
    p.add_argument("--env", choices=ENVIRONMENTS, default="dev")
    p.set_defaults(func=cmd_where)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
