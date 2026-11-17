"""Create a tenant and its first tenant admin (M2a, #92).

Run from the repo root with the API's PG* environment set:
    python scripts/create_tenant_admin.py --tenant acme --name "Acme Pty Ltd" --username alice

The password is read from TE_ADMIN_PASSWORD if set, otherwise prompted for.
Brings the database to the current migration first, then creates the tenant's schema.

If the tenant already exists the script does not fail. It says what exists and asks whether
to use it:
  - the username is already a member of it: there is nothing to create, so it offers to use
    the tenant as it is;
  - the tenant exists but the username does not: it offers to add that username as a tenant
    admin of the existing tenant, and then asks for the new account's password.
Answer y to accept. Anything else changes nothing. With no terminal, or to skip the question,
pass --use-existing. --name is ignored for a tenant that already exists (it is not renamed).

A username that already belongs to an account outside that tenant is never reused: usernames,
and their passwords, are shared across all tenants, so using one would hand that account
admin rights here. Choose another --username.

The check comes before the password prompt, so nobody types a password for something that
cannot be created. To change the password of an existing account, use
scripts/reset_password.py.

Exit status: 0 created, or an existing tenant used; 1 refused or declined, nothing changed;
2 password too short.
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


def interactive() -> bool:
    """True when a person is at the terminal and can be asked a question."""
    return sys.stdin.isatty() and sys.stderr.isatty()


def confirm(question: str) -> bool:
    """Ask a yes/no question on stderr; only y or yes accepts. No answer means no."""
    print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip().lower() in ("y", "yes")
    except EOFError:
        return False


def refusal(username: str, found: accounts.Existing) -> str | None:
    """Why this admin can never be created here, even by using an existing tenant."""
    if found.user and not found.member:
        return (f"The username '{username}' is already in use (usernames are unique across all tenants), "
                "so it was not created again. Nothing was changed.\n"
                "Choose a different --username.")
    return None


def describe_existing(tenant: str, username: str, found: accounts.Existing) -> tuple[str, str]:
    """(what already exists, the question to ask) when the tenant is already there."""
    if found.member:
        return (f"Tenant '{tenant}' already exists, and '{username}' is already a member of it.",
                f"Use the existing tenant '{tenant}' as it is? (nothing will be created)")
    return (f"Tenant '{tenant}' already exists, and '{username}' is not in it yet.",
            f"Use the existing tenant '{tenant}' and add '{username}' as a tenant admin?")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", required=True, help="tenant slug: lowercase letters, digits, underscore")
    ap.add_argument("--name", required=True, help="tenant display name (ignored if the tenant already exists)")
    ap.add_argument("--username", required=True)
    ap.add_argument("--allow-self-approval", action="store_true",
                    help="let members approve data they uploaded or submitted (for a tenant with a single user)")
    ap.add_argument("--use-existing", action="store_true",
                    help="if the tenant already exists, use it without asking")
    args = ap.parse_args(argv)
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
            message = refusal(args.username, found)
            if message:
                print(message, file=sys.stderr)
                return 1
            if found.tenant:
                what, question = describe_existing(args.tenant, args.username, found)
                print(what, file=sys.stderr)
                if not args.use_existing:
                    if not interactive():
                        print("Nothing was changed. To use the existing tenant without being asked, "
                              "run again with --use-existing.", file=sys.stderr)
                        return 1
                    if not confirm(question):
                        print("Nothing was changed.", file=sys.stderr)
                        return 1
            # Asked only now, after the checks, so a password is never typed for nothing.
            # A member that already exists keeps the password it has.
            password = None
            if not found.member:
                password = env_password or getpass.getpass("Password for the new admin: ")
                if len(password) < accounts.MIN_PASSWORD:
                    print(too_short, file=sys.stderr)
                    return 2
            try:
                with conn.cursor() as cur:
                    if found.tenant:
                        tenant_id = accounts.tenant_id(cur, args.tenant)
                    else:
                        tenant_id = accounts.create_tenant(cur, args.tenant, args.name)
                    if not found.member:
                        user_id = accounts.create_user(cur, args.username, password)
                        accounts.add_membership(cur, user_id, tenant_id, "tenant_admin")
                    if args.allow_self_approval:
                        accounts.set_self_approval(cur, args.tenant, True)
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                # The checks above passed, then someone else created the same tenant or user.
                conn.rollback()
                print(f"Tenant '{args.tenant}' or username '{args.username}' was created by someone else "
                      "while this ran. Nothing was changed.", file=sys.stderr)
                return 1
        migrate_tenant(args.tenant)
    finally:
        db.close_pool()
    schema = schema_for(args.tenant)
    if not found.tenant:
        print(f"Created tenant '{args.tenant}' (schema {schema}) with tenant admin '{args.username}'.")
    elif found.member:
        print(f"Using the existing tenant '{args.tenant}' (schema {schema}). Nothing was created: "
              f"'{args.username}' is already a member.\n"
              f"To set a new password for '{args.username}': "
              f"python scripts/reset_password.py --username {args.username}")
    else:
        print(f"Added tenant admin '{args.username}' to the existing tenant '{args.tenant}' (schema {schema}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
