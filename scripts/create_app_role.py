"""Create or update the API's runtime database role (M3d, #107).

Run once from the repo root, with the owner's PG* environment set (the same
settings start-api.ps1 uses):
    python scripts/create_app_role.py

What it does:
- creates the login role (default te_app) with a new random password, or gives
  an existing one a new password;
- lets the owner hand tables to it (GRANT te_app TO <owner>);
- brings every schema to the current migration and applies the grants: read and
  write on ordinary tables, read and insert only on the audit and upload tables;
- writes APP_DB_USER and APP_DB_PASSWORD to an env file only you can read
  (default ~/.te-migration/app-db.env), which start-api.ps1 loads.

The password is never printed. Set TE_APP_DB_PASSWORD to choose it yourself.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg2 import sql  # noqa: E402

from api import db  # noqa: E402
from api.config import settings  # noqa: E402

DEFAULT_ENV_FILE = Path.home() / ".te-migration" / "app-db.env"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--role", default="te_app")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = ap.parse_args()
    if args.role == settings.PG_USER:
        print("The runtime role must differ from the owner (PGUSER).", file=sys.stderr)
        return 2
    password = os.environ.get("TE_APP_DB_PASSWORD") or secrets.token_urlsafe(32)

    with db.owner_connect() as conn, conn.cursor() as cur:
        role, pw = sql.Identifier(args.role), sql.Literal(password)
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (args.role,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
                    .format(role, pw))
        cur.execute(sql.SQL("GRANT {} TO {}").format(role, sql.Identifier(settings.PG_USER)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(settings.PG_DATABASE), role))
        conn.commit()

    settings.APP_DB_USER, settings.APP_DB_PASSWORD = args.role, password
    db.bootstrap()   # migrations, then grants on every schema, tenants included

    args.env_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"APP_DB_USER={args.role}\nAPP_DB_PASSWORD={password}\n")
    print(f"Role '{args.role}' is ready ({'created' if verb == 'CREATE' else 'new password set'}). Its settings are in {args.env_file}; "
          "start-api.ps1 loads them. Restart the API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
