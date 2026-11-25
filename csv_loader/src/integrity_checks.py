"""Post-load integrity audits.

These run *after* the staging table has been populated and *before* (or after)
promotion. They are the substantive correctness checks: row counts, column
contents, NOT NULL audits, duplicate keys, and per-row spot checks.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

import pandas as pd
from psycopg2 import sql as pgsql

from .config import JobConfig
from .reporting import StageResult


def _scalar(conn, query, params: tuple = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    return row[0] if row else None


def run_integrity_checks(
    conn, job: JobConfig, csv_df: pd.DataFrame, rows_in_staging: int
) -> StageResult:
    stage = StageResult(stage="integrity")

    # Resolve the primary-key column once (BUG-03). The CSV side is indexed
    # against the DataFrame; the DB side is used in SQL identifiers.
    pk_csv = job.primary_key_csv
    pk_db = job.primary_key_db

    # -- 1. Row count parity ------------------------------------------------
    csv_rows = len(csv_df)
    dropped = csv_rows - rows_in_staging
    pct_dropped = (dropped / csv_rows * 100.0) if csv_rows else 0.0
    stage.record(
        "row_count_parity",
        pct_dropped <= job.thresholds.max_pct_rows_dropped,
        detail=(
            f"csv={csv_rows}, staging={rows_in_staging}, "
            f"dropped={dropped} ({pct_dropped:.2f}%)"
        ),
        metric={
            "csv_rows": csv_rows,
            "staging_rows": rows_in_staging,
            "dropped": dropped,
            "dropped_pct": pct_dropped,
        },
    )

    # -- 2. NOT NULL audit (post-load) -------------------------------------
    for col in job.required_columns:
        q = pgsql.SQL("SELECT COUNT(*) FROM {} WHERE {} IS NULL").format(
            pgsql.Identifier(job.staging_table),
            pgsql.Identifier(col.db_column),
        )
        nulls = _scalar(conn, q)
        stage.record(
            f"db_not_null.{col.db_column}",
            nulls == 0,
            detail=f"{nulls} null rows in required column",
            metric={"null_count": nulls},
        )

    # -- 3. Duplicate primary keys -----------------------------------------
    dup_q = pgsql.SQL(
        "SELECT COUNT(*) FROM ("
        "  SELECT {} FROM {} GROUP BY {} HAVING COUNT(*) > 1"
        ") AS dups"
    ).format(
        pgsql.Identifier(pk_db),
        pgsql.Identifier(job.staging_table),
        pgsql.Identifier(pk_db),
    )
    dup_count = _scalar(conn, dup_q) or 0
    stage.record(
        "no_duplicate_pk",
        dup_count == 0,
        detail=f"{dup_count} duplicate {pk_db} groups in staging",
        metric={"duplicate_groups": dup_count},
    )

    # -- 4. Unique-column audit --------------------------------------------
    for col in job.columns:
        if not col.unique:
            continue
        u_q = pgsql.SQL(
            "SELECT COUNT(*) FROM ("
            "  SELECT {} FROM {} WHERE {} IS NOT NULL"
            "  GROUP BY {} HAVING COUNT(*) > 1"
            ") AS dups"
        ).format(
            pgsql.Identifier(col.db_column),
            pgsql.Identifier(job.staging_table),
            pgsql.Identifier(col.db_column),
            pgsql.Identifier(col.db_column),
        )
        u_dups = _scalar(conn, u_q) or 0
        stage.record(
            f"unique_column.{col.db_column}",
            u_dups == 0,
            detail=f"{u_dups} duplicate values in unique column",
            metric={"duplicate_groups": u_dups},
        )

    # -- 5. Column-level value comparison ----------------------------------
    null_set = set(job.null_values) | {""}
    for col in job.columns:
        if col.csv_name not in csv_df.columns:
            continue

        with conn.cursor() as cur:
            cur.execute(pgsql.SQL("SELECT {}, {} FROM {}").format(
                pgsql.Identifier(pk_db),
                pgsql.Identifier(col.db_column),
                pgsql.Identifier(job.staging_table),
            ))
            db_rows = cur.fetchall()
        db_map = {
            _normalize(r[0], job.primary_key_spec.type): r[1]
            for r in db_rows
        }

        # Build the CSV map keyed by the PK's normalized value so we can
        # join numerics-as-strings against numerics-as-Decimals.
        csv_map: Dict[Any, Any] = {}
        for _, row in csv_df.iterrows():
            raw_key = row[pk_csv]
            key = _normalize(
                None if (pd.isna(raw_key) or raw_key in null_set) else raw_key,
                job.primary_key_spec.type,
            )
            raw = row[col.csv_name]
            csv_map[key] = (
                None if (pd.isna(raw) or raw in null_set) else raw
            )

        mismatches: List[Dict[str, Any]] = []
        for k, csv_v in csv_map.items():
            db_v = db_map.get(k, "__missing__")
            if db_v == "__missing__":
                mismatches.append({"pk": k, "csv": csv_v, "db": "__missing__"})
            elif _normalize(csv_v, col.type) != _normalize(db_v, col.type):
                mismatches.append({"pk": k, "csv": csv_v, "db": db_v})
            if len(mismatches) >= 5:
                break

        stage.record(
            f"column_value_match.{col.db_column}",
            not mismatches,
            detail=(
                f"All {len(csv_map)} values match" if not mismatches
                else f"{len(mismatches)} mismatch(es): {mismatches}"
            ),
        )

    # -- 6. Per-row spot checks (from config) ------------------------------
    type_lookup = {c.db_column: c.type for c in job.columns}
    for i, sc in enumerate(job.spot_checks, start=1):
        where_clause = pgsql.SQL(" AND ").join(
            pgsql.SQL("{} = %s").format(pgsql.Identifier(k))
            for k in sc.row_match.keys()
        )
        params = tuple(sc.row_match.values())
        cols_select = pgsql.SQL(", ").join(
            pgsql.Identifier(k) for k in sc.assert_values.keys()
        )
        spot_q = pgsql.SQL("SELECT {} FROM {} WHERE {}").format(
            cols_select, pgsql.Identifier(job.staging_table), where_clause,
        )
        with conn.cursor() as cur:
            cur.execute(spot_q, params)
            row = cur.fetchone()

        if row is None:
            stage.record(
                f"spot_check_{i}.row_found",
                False,
                detail=f"No row matches {sc.row_match}",
            )
            continue

        for idx, (k, expected) in enumerate(sc.assert_values.items()):
            actual = row[idx]
            t = type_lookup.get(k, "text")
            ok = _normalize(actual, t) == _normalize(expected, t)
            stage.record(
                f"spot_check_{i}.{k}",
                ok,
                detail=(
                    f"expected={expected!r} ({_normalize(expected, t)!r}), "
                    f"actual={actual!r} ({_normalize(actual, t)!r})"
                ),
            )

    return stage


# ---------------------------------------------------------------------------
# Type-aware value normalization. Used both for column-by-column equality
# checks and for spot-check assertions. Always returns a comparable Python
# value or None.

def _normalize(v: Any, type_: str) -> Any:
    """Normalize a value before comparison.

    BUG-04 / BUG-14: the previous version handled only integer/numeric/boolean
    and silently fell through to ``str(v)`` for everything else. This version
    has explicit branches for date, timestamp, and uuid so common comparisons
    like ``Decimal('1250.50') == 1250.5`` and
    ``datetime.date(2024,1,15) == '2024-01-15'`` succeed.
    """
    if v is None:
        return None
    if isinstance(v, str) and v == "":
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None

    t = (type_ or "").lower()

    try:
        if t in ("integer", "bigint", "smallint"):
            if isinstance(v, bool):  # bool is a subclass of int — disambiguate
                return int(v)
            if isinstance(v, (int,)):
                return int(v)
            return int(Decimal(str(v)))
        if t == "numeric":
            if isinstance(v, Decimal):
                return Decimal(v).normalize()
            return Decimal(str(v)).normalize()
        if t == "boolean":
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("t", "true", "1", "yes", "y")
        if t == "date":
            if isinstance(v, _dt.datetime):
                return v.date()
            if isinstance(v, _dt.date):
                return v
            return _dt.date.fromisoformat(str(v).strip()[:10])
        if t == "timestamp":
            if isinstance(v, _dt.datetime):
                return v
            s = str(v).strip().replace("Z", "+00:00")
            try:
                return _dt.datetime.fromisoformat(s)
            except ValueError:
                # Fallback: ISO date only
                return _dt.datetime.fromisoformat(s[:19])
        if t == "uuid":
            if isinstance(v, _uuid.UUID):
                return v
            return _uuid.UUID(str(v))
    except (TypeError, ValueError, InvalidOperation):
        # Coercion failed — fall through to a string compare so the caller
        # at least sees a deterministic mismatch rather than an exception.
        return str(v)

    # Default: string compare with whitespace trimmed.
    return str(v).strip()
