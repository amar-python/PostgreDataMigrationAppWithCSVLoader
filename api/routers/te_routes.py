"""T&E schema endpoints — table list with row counts for the fixed 12 tables."""

from fastapi import APIRouter
from psycopg2 import sql

from api.config import TE_TABLES, settings
from api.db import Conn

router = APIRouter(prefix="/api/te", tags=["te"])


@router.get("/tables")
def te_tables() -> list[dict]:
    out = []
    with Conn() as conn:
        with conn.cursor() as cur:
            for table in TE_TABLES:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                    """,
                    (settings.TE_SCHEMA, table),
                )
                exists = cur.fetchone()[0] > 0
                count = 0
                if exists:
                    cur.execute(
                        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                            sql.Identifier(settings.TE_SCHEMA), sql.Identifier(table)
                        )
                    )
                    count = cur.fetchone()[0]
                out.append({"table": table, "exists": exists, "rowCount": count})
    return out
