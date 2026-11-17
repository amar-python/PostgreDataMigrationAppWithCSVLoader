"""Create a tenant and its first tenant admin (M2a, #92).

Run from the repo root with the API's PG* environment set:
    python scripts/create_tenant_admin.py --tenant acme --name "Acme Pty Ltd" --username alice

The password is read from TE_ADMIN_PASSWORD if set, otherwise prompted for.
Brings the database to the current migration first, then creates the tenant's schema.

If the tenant or the username already exists, it says so and changes nothing. That check
comes before the password prompt, so nobody types a password for something that cannot be
created. To change the password of an existing account, use scripts/reset_password.py.

Exit status: 0 created; 1 refused because it already exists; 2 password too short.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import psycopg2.errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402
from api.services import accounts  # noqa: E402
from api.tenancy import migrate_tenant, schema_for  # noqa: E402


def refusal(tenant: str, username: str, found: accounts.Existing) -> str | None:
    """Why this tenant and admin cannot be created, or None if they can."""
    if found.member:
        return (f"Tenant '{tenant}' already exists and '{username}' is already a member of it. "
                "Nothing was changed.\n"
                f"To set a new password for '{username}': "
                f"python scripts/reset_password.py --username {username}")
    if found.tenant:
        return (f"Tenant '{tenant}' already exists, so it was not created again. Nothing was changed.\n"
                "This script creates new tenants. Use a different --tenant, or set the password of an "
                "existing member with: python scripts/reset_password.py --username NAME")
    if found.user:
        return (f"The username '{username}' is already in use (usernames are unique across all tenants). "
                "Nothing was changed.\n"
                "Choose a different --username.")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", required=True, help="tenant slug: lowercase letters, digits, underscore")
    ap.add_argument("--name", required=True, help="tenant display name")
    ap.add_argument("--username", required=True)
    ap.add_argument("--allow-self-approval", action="store_true",
                    help="let members approve data they uploaded or submitted (for a tenant with a single user)")
    args = ap.parse_args()
    too_short = f"Password must be at least {accounts.MIN_PASSWORD} characters."
    env_password = os.environ.get("TE_ADMIN_PASSWORD")
    if env_password and len(env_password) < accounts.MIN_PASSWORD:
        print(too_short, file=sys.stderr)  # before the database is touched
        return 2
    db.init_pool()
    db.bootstrap()
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                found = accounts.existing(cur, args.tenant, args.username)
            conn.rollback()  # end the read now: a prompt can take minutes, and no session should sit open
            message = refusal(args.tenant, args.username, found)
            if message:
                print(message, file=sys.stderr)
                return 1
            # Asked only now, after the check, so a password is never typed for nothing.
            password = env_password or getpass.getpass("Password for the new admin: ")
            if len(password) < accounts.MIN_PASSWORD:
                print(too_short, file=sys.stderr)
                return 2
            try:
                with conn.cursor() as cur:
                    tenant_id = accounts.create_tenant(cur, args.tenant, args.name)
                    user_id = accounts.create_user(cur, args.username, password)
                    accounts.add_membership(cur, user_id, tenant_id, "tenant_admin")
                    if args.allow_self_approval:
                        accounts.set_self_approval(cur, args.tenant, True)
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                # The check above passed, then someone else created the same tenant or user.
                conn.rollback()
                print(f"Tenant '{args.tenant}' or username '{args.username}' was created by someone else "
                      "while this ran. Nothing was changed.", file=sys.stderr)
                return 1
        migrate_tenant(args.tenant)
    finally:
        db.close_pool()
    print(f"Created tenant '{args.tenant}' (schema {schema_for(args.tenant)}) "
          f"with tenant admin '{args.username}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
