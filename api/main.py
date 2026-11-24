"""PostgreDataMigrationApp API — FastAPI backend for the CSV migration frontend.

Run (from the repo root):
    pip install -r api/requirements.txt
    set PGPASSWORD=  # or $env:PGPASSWORD="" on PowerShell
    python -m uvicorn api.main:app --reload --port 8000
    Interactive docs: http://localhost:8000/docs
"""

import logging
import os
from contextlib import asynccontextmanager

import psycopg2.pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import db, oidc, policy
from api.bodylimit import BodyLimitMiddleware
from api.config import settings
from api.ratelimit import rate_limit_middleware
from api.routers import (audit_routes, auth_routes, csv_routes, import_routes, policy_routes, review_routes,
                         te_routes)
from api.services import accounts

logger = logging.getLogger(__name__)


def assert_auth_configured(api_env: str, allow_anonymous: bool) -> None:
    """Refuse to start when anonymous access is asked for outside dev (O-03, #298).

    Split out of ``lifespan`` so the rule can be unit-tested without a database:
    ``lifespan`` also opens the connection pool, which would make every test of
    this check an integration test.

    Data endpoints need a signed-in session. Only ``API_ENV=dev`` may opt in to
    anonymous access with ``API_ALLOW_ANONYMOUS``; with any other ``API_ENV``
    the opt-in is a misconfiguration and this raises RuntimeError rather than
    quietly ignoring it.
    """
    if allow_anonymous and api_env != "dev":
        raise RuntimeError(
            f"API_ALLOW_ANONYMOUS is set but API_ENV is '{api_env}'. "
            "Refusing to start: anonymous access is for local development only. "
            "Unset API_ALLOW_ANONYMOUS; callers sign in (POST /api/auth/login)."
        )


def docs_urls(api_env: str) -> dict:
    """FastAPI arguments that serve the interactive docs and the OpenAPI schema only in dev (#291, BR-54).

    ``/docs``, ``/redoc`` and ``/openapi.json`` list every route to anyone who can reach the port, with no key
    needed. Outside dev they are switched off (404). They are fixed when the app is created, so this runs at import.
    """
    if api_env == "dev":
        return {}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def _purge_old_sessions() -> None:
    """Delete session rows that ended long ago (#296). Housekeeping: a failure is logged and never stops the API."""
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                removed = accounts.purge_sessions(cur)
            conn.commit()
        if removed:
            logger.info("Purged %d ended session row(s).", removed)
    except Exception:  # noqa: BLE001
        logger.warning("Could not purge old sessions at start-up; scripts/purge_sessions.py can do it later.",
                       exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # O-03 / #298: fail closed. Anonymous access is refused outside dev, and even in dev it needs the explicit
    # API_ALLOW_ANONYMOUS opt-in; without it every data endpoint answers 401 until the caller signs in.
    assert_auth_configured(settings.API_ENV, settings.API_ALLOW_ANONYMOUS)
    oidc.check_config()
    policy.check_config(settings.DATA_CLASSIFICATION, settings.AUDIT_RETENTION_YEARS)
    if settings.API_ALLOW_ANONYMOUS:
        logger.warning(
            "!!! ANONYMOUS ACCESS IS ON (API_ALLOW_ANONYMOUS with API_ENV=dev): data endpoints answer without "
            "sign-in, with no tenant, no role checks and full delete rights. Local development and tests only. !!!"
        )
    if os.environ.get("API_KEY"):
        # #298: the shared key was retired. Say so, so an old install's leftover variable is not mistaken for
        # protection. Nothing about its value is logged.
        logger.warning(
            "API_KEY is set but no longer used: the shared X-API-Key was retired (#298). "
            "Scripts sign in with POST /api/auth/login and send Authorization: Bearer <token>."
        )
    if not settings.PG_PASSWORD:
        logger.warning(
            "PGPASSWORD is not set - connecting with an empty password. "
            "Fine for local dev; set PGPASSWORD before deploying anywhere else."
        )
    db.init_pool()
    db.bootstrap()
    _purge_old_sessions()
    yield
    db.close_pool()


app = FastAPI(
    title="PostgreDataMigrationApp API",
    version="1.0.0",
    description="CSV migration pipeline: preview, validate, load (dynamic tables or fixed T&E schema).",
    lifespan=lifespan,
    # BUG-035: API-key auth is applied per-router (see csv_routes.py and
    # te_routes.py). It is deliberately NOT applied at app level so external
    # uptime probes can hit /api/health without needing the shared secret.
    **docs_urls(settings.API_ENV),  # #291: no interactive docs or schema outside dev
)

# #290 (OIT-005): refuse an oversize request body before anything parses it. Added first, so it is the
# innermost middleware: it still sits in front of every route, and its 413 passes back out through
# CORSMiddleware, which a browser needs in order to read the status at all.
app.add_middleware(BodyLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # PUT: review changes (M4, #108)
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],  # the last: M6 import (#110)
    expose_headers=["X-Data-Classification"],  # so the browser can read the marking (M7)
)

# O-03: rate limiting. Registered after CORSMiddleware so it sits outside it in
# Starlette's onion (last added = outermost) and a 429 still carries CORS headers,
# which the browser needs in order to read the status at all.
app.middleware("http")(rate_limit_middleware)

app.include_router(auth_routes.router)
app.include_router(csv_routes.router)
app.include_router(review_routes.router)
app.include_router(import_routes.router)
app.include_router(te_routes.router)
app.include_router(audit_routes.router)
app.include_router(policy_routes.router)


@app.exception_handler(psycopg2.pool.PoolError)
def pool_exhausted_handler(request: Request, exc: psycopg2.pool.PoolError) -> JSONResponse:
    logger.warning("DB connection pool exhausted: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Server busy, please retry shortly."})


@app.get("/api/health", tags=["health"])
def health() -> dict:
    # BUG-031: verify the uploads schema is present, not just that Postgres is
    # up. Otherwise a half-bootstrapped API reports "ok" and then every /upload
    # call throws UndefinedTable.
    from psycopg2 import sql as _sql
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                pg_version = cur.fetchone()[0]
                cur.execute(
                    _sql.SQL("SELECT 1 FROM {}.csv_files LIMIT 0").format(
                        _sql.Identifier(settings.UPLOADS_SCHEMA)
                    )
                )
        body: dict = {"status": "ok"}
        # #291 (BR-54): /api/health is open to anyone who can reach the port, so outside dev it says
        # only whether the API is up. The database name, host, version and schema are dev details.
        if settings.API_ENV == "dev":
            body.update(
                database=settings.PG_DATABASE,
                host=f"{settings.PG_HOST}:{settings.PG_PORT}",
                postgres=pg_version.split(" on ")[0],
                uploads_schema=settings.UPLOADS_SCHEMA,
            )
        return body
    except Exception as exc:  # noqa: BLE001 — surface DB reachability to the UI
        # Log the real exception server-side, but don't return it: /api/health
        # is deliberately unauthenticated (see BUG-035 comment above), and
        # psycopg2's OperationalError text can include host/port/user details.
        logger.warning("Health check failed: %s", exc)
        degraded: dict = {"status": "degraded"}
        if settings.API_ENV == "dev":
            degraded["error"] = "Database is unreachable or not fully bootstrapped."
        return degraded
