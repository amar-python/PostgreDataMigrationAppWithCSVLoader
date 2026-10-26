"""T&E schema endpoints — table list with row counts for the fixed 12 tables."""

from fastapi import APIRouter, Depends

from api.auth import tenant_scope
from api.config import TE_TABLES
from api.tenancy import te_schema
from api.db import Conn

# BUG-035: auth is applied per-router (see csv_routes.py for the rationale).
router = APIRouter(
    prefix="/api/te",
    tags=["te"],
    dependencies=[Depends(tenant_scope)],
)


@router.get("/tables")
def te_tables() -> list[dict]:
    # BUG-042: this used to run 1-2 queries per table (24 for the 12-table
    # whitelist) — a COUNT(*) existence check plus a full COUNT(*) scan.
    # Two queries total instead: existence from information_schema.tables,
    # row counts from pg_stat_user_tables (the planner's own live-tuple
    # estimate — approximate, refreshed by autovacuum/ANALYZE, but fine for a
    # dashboard figure and vastly cheaper than a real COUNT(*) at scale).
    tables = list(TE_TABLES)
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = %s AND table_name = ANY(%s)
                """,
                (te_schema(), tables),
            )
            existing = {r[0] for r in cur.fetchall()}
            cur.execute(
                """
                SELECT relname, n_live_tup FROM pg_stat_user_tables
                WHERE schemaname = %s AND relname = ANY(%s)
                """,
                (te_schema(), tables),
            )
            row_counts = {r[0]: max(r[1], 0) for r in cur.fetchall()}
    return [
        {
            "table": table,
            "exists": table in existing,
            "rowCount": row_counts.get(table, 0) if table in existing else 0,
        }
        for table in TE_TABLES
    ]
