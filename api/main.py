"""PostgreDataMigrationApp API — FastAPI backend for the CSV migration frontend.

Run (from the repo root):
    pip install -r api/requirements.txt
    set PGPASSWORD=  # or $env:PGPASSWORD="" on PowerShell
    python -m uvicorn api.main:app --reload --port 8000
    Interactive docs: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

import psycopg2.pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import db
from api.config import settings
from api.routers import audit_routes, csv_routes, te_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.API_KEY:
        logger.warning(
            "API_KEY is not set - every endpoint is unauthenticated. "
            "Set the API_KEY environment variable before deploying anywhere "
            "reachable beyond localhost."
        )
    else:
        # Fingerprint (first 4 chars + length) so mismatches with the frontend's
        # VITE_API_KEY are diagnosable without leaking the secret to the log.
        # Fixes BUG-006 in docs/BUG_REPORT.md.
        fp = settings.API_KEY[:4] + "..." if len(settings.API_KEY) >= 4 else "***"
        logger.info(
            "API_KEY is set (fingerprint: %s, length: %d). "
            "Frontend must send matching VITE_API_KEY via the X-API-Key header.",
            fp, len(settings.API_KEY),
        )
    if not settings.PG_PASSWORD:
        logger.warning(
            "PGPASSWORD is not set - connecting with an empty password. "
            "Fine for local dev; set PGPASSWORD before deploying anywhere else."
        )
    db.init_pool()
    db.bootstrap()
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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(csv_routes.router)
app.include_router(te_routes.router)
app.include_router(audit_routes.router)


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
        return {
            "status": "ok",
            "database": settings.PG_DATABASE,
            "host": f"{settings.PG_HOST}:{settings.PG_PORT}",
            "postgres": pg_version.split(" on ")[0],
            "uploads_schema": settings.UPLOADS_SCHEMA,
        }
    except Exception as exc:  # noqa: BLE001 — surface DB reachability to the UI
        # Log the real exception server-side, but don't return it: /api/health
        # is deliberately unauthenticated (see BUG-035 comment above), and
        # psycopg2's OperationalError text can include host/port/user details.
        logger.warning("Health check failed: %s", exc)
        return {"status": "degraded", "error": "Database is unreachable or not fully bootstrapped."}
