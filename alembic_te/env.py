"""Alembic environment for the T&E tables inside ONE tenant schema (#184).

A second chain, separate from ``alembic/``: that one versions the uploads objects
(``csv_files``, ``audit_log``, ...); this one versions the twelve fixed T&E tables
that api/tenancy.py clones into each tenant from the deployment's template schema.
Its version table is ``alembic_version_te``, inside the tenant schema, so each tenant
carries its own T&E schema version.

It never runs from a command line: the target schema comes from the caller
(``cfg.attributes["schema"]``), and api/tenancy.py serialises callers per tenant.
"""

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import settings  # noqa: E402

VERSION_TABLE = "alembic_version_te"

if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) migrations are not supported; run against a database.")

schema = context.config.attributes.get("schema")
if not schema:
    raise RuntimeError("T&E migrations run against one tenant schema. Use api.tenancy.migrate_tenant(slug).")

url = URL.create(
    "postgresql+psycopg2",
    username=settings.PG_USER,
    password=settings.PG_PASSWORD or None,
    host=settings.PG_HOST,
    port=settings.PG_PORT,
    database=settings.PG_DATABASE,
)
engine = create_engine(url, poolclass=NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, version_table=VERSION_TABLE, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()
