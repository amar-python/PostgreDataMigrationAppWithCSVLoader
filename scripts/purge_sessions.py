"""Delete ended sign-in sessions from the database (#296, BR-36).

Removes the rows of sessions that expired, were signed out or ended by a password change, or went idle, once they
ended more than SESSION_PURGE_GRACE_DAYS ago (default 1). A live session is never touched. The API does this once each
time it starts; run this on a schedule (cron, or a Container Apps job) for a deployment that stays up for weeks.
Run from the repo root with the API's PG* environment set, after the API has started once on this version (it adds
the column the purge reads):
    python scripts/purge_sessions.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402
from api.config import settings  # noqa: E402
from api.services import accounts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    db.init_pool()
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                removed = accounts.purge_sessions(cur)
            conn.commit()
    finally:
        db.close_pool()
    print(f"Purged {removed} session(s) that ended more than {settings.SESSION_PURGE_GRACE_DAYS} day(s) ago.")
    return 0


if __name__ == "__main__":
    sys.exit(db.run_cli(main))
