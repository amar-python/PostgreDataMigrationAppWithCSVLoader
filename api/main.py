"""PostgreDataMigrationApp API — FastAPI backend for the CSV migration frontend.

Run (from the api/ directory):
    pip install -r requirements.txt
    set PGPASSWORD=<pw>       # or export on Mac/Linux
    uvicorn main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.config import settings
from api.routers import csv_routes, te_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    try:
        db.bootstrap()
        yield
    finally:
        db.close_pool()


app = FastAPI(
    title="PostgreDataMigrationApp API",
    version="1.0.0",
    description="CSV migration pipeline: preview, validate, load (dynamic tables or fixed T&E schema).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(csv_routes.router)
app.include_router(te_routes.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    try:
        with db.Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                pg_version = cur.fetchone()[0]
        return {
            "status": "ok",
            "database": settings.PG_DATABASE,
            "host": f"{settings.PG_HOST}:{settings.PG_PORT}",
            "postgres": pg_version.split(" on ")[0],
        }
    except Exception as exc:  # noqa: BLE001 — surface DB reachability to the UI
        return {"status": "degraded", "error": str(exc)}
