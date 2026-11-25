"""Alembic environment for the uploads schema.

Connection settings come from api/config.py, the same values the API pool uses.
The version table lives inside the uploads schema, so each schema carries its
own migration state (this matters once there is one schema per tenant).
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import settings  # noqa: E402

if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) migrations are not supported; run against a database.")

url = URL.create(
    "postgresql+psycopg2",
    username=settings.PG_USER,
    password=settings.PG_PASSWORD.get_secret_value() or None,
    host=settings.PG_HOST,
    port=settings.PG_PORT,
    database=settings.PG_DATABASE,
)
schema = settings.UPLOADS_SCHEMA

# #286 (OIT-001, BR-50): every API process runs these migrations at start-up. Two processes starting
# together raced on CREATE SCHEMA and on each migration, and the loser's start-up failed. A session-level
# advisory lock serialises them across processes: the second waits, then finds the schema at head and
# does nothing. One key for every run of this env (all uploads schemas and the control schema its
# migrations create), so tenant upgrades and start-up upgrades cannot interleave either. Advisory locks
# are per database; the lock is released explicitly and, failing that, when the connection closes.
LOCK_KEY = "alembic:uploads-env"

engine = create_engine(url, poolclass=NullPool)
with engine.connect() as connection:
    connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": LOCK_KEY})
    connection.commit()
    try:
        quoted = connection.dialect.identifier_preparer.quote(schema)
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted}"))
        connection.commit()
        context.configure(connection=connection, version_table_schema=schema)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": LOCK_KEY})
        connection.commit()
