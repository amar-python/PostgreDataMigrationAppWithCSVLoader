"""Break-glass password reset for a local account (#117).

For an operator with database access, when no tenant admin can sign in. It sets
the password, clears any lockout (#102) and ends all of the user's sessions.
Run from the repo root with the API's PG* environment set:
    python scripts/reset_password.py --username alice

The new password is read from TE_NEW_PASSWORD if set, otherwise prompted for.
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--username", required=True)
    args = ap.parse_args(argv)
    password = os.environ.get("TE_NEW_PASSWORD") or getpass.getpass(f"New password for {args.username}: ")
    if len(password) < accounts.MIN_PASSWORD:
        print(f"Password must be at least {accounts.MIN_PASSWORD} characters.", file=sys.stderr)
        return 2
    db.init_pool()
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                found = accounts.set_password(cur, args.username, password)
            conn.commit()
    finally:
        db.close_pool()
    if not found:
        print(f"No user '{args.username}'.", file=sys.stderr)
        return 1
    print(f"Password reset for '{args.username}'; lockout cleared and all sessions ended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
