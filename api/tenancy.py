"""Per-request tenant schema routing (M2b, #93, BR-36; decision 6: schema per tenant).

Each tenant's registry, audit log and uploaded tables live in schema
``tenant_<slug>``. A request signed in to a tenant runs with that schema set
here; ``uploads_schema()`` and ``te_schema()`` read it. A request without a
session (API-key or dev) keeps the deployment's default schemas.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar

from api.config import settings

_current: ContextVar[str | None] = ContextVar("tenant_schema", default=None)
_migrate_lock = threading.Lock()


def schema_for(slug: str) -> str:
    """Schema name for a tenant slug. The slug CHECK in control.tenants keeps it a safe identifier."""
    return f"tenant_{slug}"


def current_schema() -> str | None:
    return _current.get()


def uploads_schema() -> str:
    return _current.get() or settings.UPLOADS_SCHEMA


def te_schema() -> str:
    # ponytail: per-tenant T&E tables arrive in #99; until then a tenant's
    # T&E requests are refused before reaching this (csv_routes.upload).
    return _current.get() or settings.TE_SCHEMA


@contextmanager
def scoped(schema: str):
    token = _current.set(schema)
    try:
        yield
    finally:
        _current.reset(token)


def migrate_tenant(slug: str) -> None:
    """Create or upgrade one tenant's schema to the latest per-tenant migration.

    Swaps settings.UPLOADS_SCHEMA while Alembic runs, so it is serialised and
    must only be called from startup or a CLI, never inside a request.
    """
    from alembic import command
    from alembic.config import Config

    from api.db import alembic_ini_path

    with _migrate_lock:
        original = settings.UPLOADS_SCHEMA
        settings.UPLOADS_SCHEMA = schema_for(slug)
        try:
            cfg = Config(str(alembic_ini_path()))
            cfg.attributes["scope"] = "tenant"
            command.upgrade(cfg, "head")
        finally:
            settings.UPLOADS_SCHEMA = original
