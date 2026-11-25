"""Schema and mapping validation.

Confirms that the live PostgreSQL target table matches the column types,
nullability, and sizes declared in the job config — *before* any rows are
loaded. This catches drift between the schema-as-coded and schema-as-deployed.
"""
from __future__ import annotations

from typing import Dict, List

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from .config import JobConfig
from .reporting import StageResult


# Loose mapping from config 'type' shorthand to the family of postgres types
# that satisfies it. We compare against `data_type` from information_schema.
TYPE_FAMILY: Dict[str, set] = {
    "integer": {"integer", "bigint", "smallint"},
    "bigint": {"bigint"},
    "smallint": {"smallint"},
    "text": {"text", "character varying", "character"},
    "varchar": {"character varying", "text", "character"},
    "date": {"date"},
    "timestamp": {"timestamp without time zone", "timestamp with time zone"},
    "numeric": {"numeric", "real", "double precision"},
    "boolean": {"boolean"},
    "json": {"json", "jsonb"},
    "uuid": {"uuid"},
}


def _fetch_table_columns(conn, table_name: str) -> List[dict]:
    """Return information_schema rows describing a table's columns.

    BUG-08: scope to the search_path so we don't conflate `public.users`
    with `archive.users`. ``current_schemas(false)`` excludes the implicit
    pg_catalog. This means the validator finds the table the same way a
    plain unqualified SQL statement would.
    """
    query = """
        SELECT column_name, data_type, is_nullable,
               character_maximum_length, column_default, table_schema
        FROM information_schema.columns
        WHERE table_name = %s
          AND table_schema = ANY(current_schemas(false))
        ORDER BY ordinal_position
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (table_name,))
        return cur.fetchall()


def validate_schema(conn, job: JobConfig) -> StageResult:
    """Compare the configured column spec against the live target table."""
    stage = StageResult(stage="schema")

    # 1. Table exists
    db_cols = _fetch_table_columns(conn, job.target_table)
    if not db_cols:
        stage.record(
            "target_table_exists", False,
            detail=(
                f"Target table '{job.target_table}' not found in search_path. "
                f"Run the schema_file before migration."
            ),
        )
        return stage
    stage.record("target_table_exists", True, detail=job.target_table)

    db_by_name = {row["column_name"]: row for row in db_cols}

    # 2. Every config column must exist
    for col in job.columns:
        if col.db_column not in db_by_name:
            stage.record(
                f"column_present.{col.db_column}", False,
                detail="Missing in target table",
            )
            continue
        stage.record(f"column_present.{col.db_column}", True)

        live = db_by_name[col.db_column]

        # 3. Type family check
        family = TYPE_FAMILY.get(col.type.lower())
        if family is None:
            stage.record(
                f"type_known.{col.db_column}", False,
                detail=f"Unknown configured type '{col.type}'",
            )
        else:
            type_ok = live["data_type"] in family
            stage.record(
                f"type_match.{col.db_column}",
                type_ok,
                detail=(
                    f"configured={col.type}, live={live['data_type']}, "
                    f"accepted={sorted(family)}"
                ),
            )

        # 4. Nullability check
        live_nullable = live["is_nullable"] == "YES"
        nullability_ok = live_nullable == col.nullable
        stage.record(
            f"nullability_match.{col.db_column}",
            nullability_ok,
            detail=f"configured nullable={col.nullable}, live nullable={live_nullable}",
        )

        # 5. Max-length compatibility (only when both sides specify a length)
        if col.max_length is not None and live["character_maximum_length"]:
            len_ok = live["character_maximum_length"] >= col.max_length
            stage.record(
                f"max_length_compatible.{col.db_column}",
                len_ok,
                detail=(
                    f"configured max_length={col.max_length}, "
                    f"live char_maximum_length={live['character_maximum_length']}"
                ),
            )

    # 6. BUG-06: surface unconfigured NOT NULL target columns that have no
    #    default and no identity. Promotion will otherwise crash with a
    #    not-null violation.
    configured = {c.db_column for c in job.columns}
    for live in db_cols:
        name = live["column_name"]
        if name in configured:
            continue
        if live["is_nullable"] == "NO" and not live["column_default"]:
            stage.record(
                f"unconfigured_required.{name}", False,
                detail=(
                    f"Target column '{name}' is NOT NULL with no default "
                    f"but is not declared in the job config. Promotion "
                    f"would fail."
                ),
            )

    return stage


def _fetch_column_types(conn, table_name: str) -> List[dict]:
    """Return each column's name and exact type, e.g. ``numeric(12,2)`` or ``character(2)``.

    #349: ``information_schema.columns.data_type`` has no precision, scale or length, so building staging from it turned
    ``NUMERIC(12,2)`` into plain ``numeric`` and ``CHAR(2)`` into ``character`` (``CHAR(1)``). ``format_type`` on the
    catalog gives the full type. ``to_regclass`` finds the table through the search_path, the same way an unqualified SQL
    statement (and ``_fetch_table_columns``, BUG-08) does.
    """
    query = """
        SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS full_type
        FROM pg_attribute a
        WHERE a.attrelid = to_regclass(quote_ident(%s))
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (table_name,))
        return cur.fetchall()


def ensure_staging_table(conn, job: JobConfig) -> None:
    """Create (or replace) a staging table with the same column types as the target table.

    Using `CREATE TABLE LIKE ... INCLUDING ALL` would copy NOT NULL constraints,
    which we do NOT want — staging accepts everything so we can validate it.
    Instead we copy column names + exact types only (#349: ``format_type``, so precision, scale and length are kept and
    a value the target would round or reject is caught in staging, not silently changed on promotion).
    """
    target = job.target_table
    staging = job.staging_table

    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(
            sql.Identifier(staging)
        ))

    cols = _fetch_column_types(conn, target)
    if not cols:
        raise RuntimeError(
            f"Cannot create staging — target table {target} does not exist"
        )

    # The type text comes from the database catalogue, not from user input.
    col_defs = [
        sql.SQL("{} {}").format(sql.Identifier(c["column_name"]), sql.SQL(c["full_type"]))
        for c in cols
    ]
    ddl = sql.SQL("CREATE TABLE {} ({})").format(
        sql.Identifier(staging), sql.SQL(", ").join(col_defs)
    )

    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
