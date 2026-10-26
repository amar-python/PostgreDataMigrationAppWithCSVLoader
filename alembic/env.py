"""Alembic environment for the uploads schema.

Connection settings come from api/config.py, the same values the API pool uses.
The version table lives inside the uploads schema, so each schema carries its
own migration state (this matters once there is one schema per tenant).
"""

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import settings  # noqa: E402

if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) migrations are not supported; run against a database.")

url = URL.create(
    "postgresql+psycopg2",
    username=settings.PG_USER,
    password=settings.PG_PASSWORD or None,
    host=settings.PG_HOST,
    port=settings.PG_PORT,
    database=settings.PG_DATABASE,
)
schema = settings.UPLOADS_SCHEMA

engine = create_engine(url, poolclass=NullPool)
with engine.connect() as connection:
    quoted = connection.dialect.identifier_preparer.quote(schema)
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted}"))
    connection.commit()
    context.configure(connection=connection, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()
