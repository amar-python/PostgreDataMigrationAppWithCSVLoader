"""Create or update the API's runtime database role (M3d, #107; RV-S3, #173).

Run once per environment from the repo root, with that environment's PG*
environment set (the same settings start-api.ps1 uses):
    python scripts/create_app_role.py --env dev

What it does:
- creates the login role for that environment (te_app_<env>) with a new random
  password, or gives an existing one a new password;
- lets the owner hand tables to it (GRANT te_app_<env> TO <owner>);
- brings every schema to the current migration and applies the grants: read and
  write on ordinary tables, read and insert only on the audit and upload tables;
- writes APP_DB_USER and APP_DB_PASSWORD to an env file only you can read
  (~/.te-migration/app-db-<env>.env), which start-api.ps1 loads.

--env is mandatory (RV-S3, #173). The role and credential file used to be the
cluster-wide te_app and ~/.te-migration/app-db.env, which breaks as soon as two
environments share one PostgreSQL cluster -- the common dev-PC setup. Running
the script for the second environment rotated the one role's password and
overwrote the one credential file, so the first environment's connections failed
silently on their next reconnect. Per-environment names mean each environment
owns its own role and its own file, and provisioning one never touches another.

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

# The four environments build/deploy_all.sh knows (its ALL_ENVS).
ENVIRONMENTS = ("dev", "test", "staging", "prod")

CREDENTIALS_DIR = Path.home() / ".te-migration"

# Pre-RV-S3 names: one role and one credential file for the whole cluster.
LEGACY_ROLE = "te_app"
LEGACY_ENV_FILE = CREDENTIALS_DIR / "app-db.env"


def role_for(env: str) -> str:
    return f"te_app_{env}"


def env_file_for(env: str) -> Path:
    return CREDENTIALS_DIR / f"app-db-{env}.env"


def retire_legacy_credentials(env: str) -> str | None:
    """Move a pre-RV-S3 ~/.te-migration/app-db.env aside, once the new file is written.

    start-api.ps1 still reads the legacy file as a fallback, so leaving it in
    place would let a dev PC keep starting the API on the old cluster-wide
    role's credentials -- exactly the stale-credential problem #173 is about.
    Renaming rather than deleting keeps the change reversible with one `mv`.
    Returns the new path, or None if there was no legacy file.
    """
    if not LEGACY_ENV_FILE.exists():
        return None
    superseded = LEGACY_ENV_FILE.with_name(LEGACY_ENV_FILE.name + f".superseded-{env}")
    os.replace(LEGACY_ENV_FILE, superseded)
    return str(superseded)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", required=True, choices=ENVIRONMENTS,
                    help="which environment this role serves. Mandatory: it names both the role "
                         "(te_app_<env>) and the credential file (~/.te-migration/app-db-<env>.env), "
                         "so two environments on one PostgreSQL cluster never share either (RV-S3, #173).")
    ap.add_argument("--role", default=None,
                    help="override the role name. Defaults to te_app_<env>.")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="override where the credentials are written. Defaults to "
                         "~/.te-migration/app-db-<env>.env. Given explicitly, the legacy "
                         "credential file is left alone.")
    args = ap.parse_args()

    role_name = args.role or role_for(args.env)
    env_file = args.env_file or env_file_for(args.env)
    if role_name == settings.PG_USER:
        print("The runtime role must differ from the owner (PGUSER).", file=sys.stderr)
        return 2
    password = os.environ.get("TE_APP_DB_PASSWORD") or secrets.token_urlsafe(32)

    with db.owner_connect() as conn, conn.cursor() as cur:
        role, pw = sql.Identifier(role_name), sql.Literal(password)
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
                    .format(role, pw))
        cur.execute(sql.SQL("GRANT {} TO {}").format(role, sql.Identifier(settings.PG_USER)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(settings.PG_DATABASE), role))
        conn.commit()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (LEGACY_ROLE,))
        legacy_role_present = cur.fetchone() is not None and role_name != LEGACY_ROLE

    settings.APP_DB_USER, settings.APP_DB_PASSWORD = role_name, password
    db.bootstrap()   # migrations, then grants on every schema, tenants included

    env_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"APP_DB_USER={role_name}\nAPP_DB_PASSWORD={password}\n")
    print(f"Role '{role_name}' is ready ({'created' if verb == 'CREATE' else 'new password set'}) "
          f"for the {args.env} environment. Its settings are in {env_file}; "
          "start-api.ps1 loads them. Restart the API.")

    if args.env_file is None:
        superseded = retire_legacy_credentials(args.env)
        if superseded:
            print(f"Moved the pre-#173 credential file aside: {superseded}. start-api.ps1 now reads "
                  f"{env_file} instead, so the API no longer starts on the old cluster-wide role.")
    if legacy_role_present:
        print(f"The pre-#173 cluster-wide role '{LEGACY_ROLE}' still exists on this server. Each "
              "environment now has its own role, so it is unused once every environment has been "
              "re-provisioned with --env. Drop it then, as the owner: "
              f'DROP OWNED BY {LEGACY_ROLE}; DROP ROLE {LEGACY_ROLE};')
    return 0


if __name__ == "__main__":
    sys.exit(main())
