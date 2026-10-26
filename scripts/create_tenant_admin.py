"""Create a tenant and its first tenant admin (M2a, #92).

Run from the repo root with the API's PG* environment set:
    python scripts/create_tenant_admin.py --tenant acme --name "Acme Pty Ltd" --username alice

The password is read from TE_ADMIN_PASSWORD if set, otherwise prompted for.
Brings the database to the current migration first, then creates the tenant's schema.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402
from api.services import accounts  # noqa: E402
from api.tenancy import migrate_tenant, schema_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", required=True, help="tenant slug: lowercase letters, digits, underscore")
    ap.add_argument("--name", required=True, help="tenant display name")
    ap.add_argument("--username", required=True)
    args = ap.parse_args()
    password = os.environ.get("TE_ADMIN_PASSWORD") or getpass.getpass("Password for the new admin: ")
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 2
    db.init_pool()
    db.bootstrap()
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                tenant_id = accounts.create_tenant(cur, args.tenant, args.name)
                user_id = accounts.create_user(cur, args.username, password)
                accounts.add_membership(cur, user_id, tenant_id, "tenant_admin")
            conn.commit()
        migrate_tenant(args.tenant)
    finally:
        db.close_pool()
    print(f"Created tenant '{args.tenant}' (schema {schema_for(args.tenant)}) "
          f"with tenant admin '{args.username}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
