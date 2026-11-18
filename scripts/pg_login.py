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
"""

from __future__ import annotations

import argparse
import getpass
import os
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


def cmd_check(args) -> int:
    host, port, user, password = _login_from_env()
    status, reason = try_login(host, port, user, password)
    who = f"{user}@{host}:{port}"
    if status == OK:
        print(f"PostgreSQL login works ({who}).")
        return 0
    if status == REFUSED:
        print(f"PostgreSQL refused the login for {who}.\n  {reason}", file=sys.stderr)
        return 2
    print(f"Could not reach PostgreSQL at {host}:{port}.\n  {reason}\n"
          "Check that the server is running on that host and port.", file=sys.stderr)
    return 3


def cmd_save(args) -> int:
    host = args.host or os.environ.get("PGHOST") or DEFAULT_HOST
    port = str(args.port or os.environ.get("PGPORT") or DEFAULT_PORT)
    user = args.user or os.environ.get("PGUSER") or DEFAULT_USER
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
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("where", help="say where the saved login is")
    p.add_argument("--env", choices=ENVIRONMENTS, default="dev")
    p.set_defaults(func=cmd_where)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
