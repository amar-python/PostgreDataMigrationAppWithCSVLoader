"""High-throughput ingestion using PostgreSQL `COPY ... FROM STDIN`.

Loads CSV rows into the staging table. The staging table mirrors the target
table's columns and types but has no NOT NULL constraints, so even a partially
malformed file lands somewhere we can inspect.

The transform path streams through a temporary file on disk rather than
materializing the whole CSV in memory (BUG-18), so it scales beyond the size
of available RAM.
"""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Tuple

from psycopg2 import sql

from .config import JobConfig


# UTF-8 byte-order mark — same handling as pre_import_validator.
_BOM = "﻿"


def _strip_bom_from_fieldnames(fieldnames):
    if not fieldnames:
        return fieldnames
    return [
        (f.lstrip(_BOM) if isinstance(f, str) else f) for f in fieldnames
    ]


def load_csv_to_staging(conn, job: JobConfig) -> Tuple[int, int]:
    """Stream a CSV into the staging table using `COPY`.

    Returns ``(rows_in_csv, rows_loaded)``.
    """
    csv_path = Path(job.source_csv)
    csv_columns = [c.csv_name for c in job.columns]
    db_columns = [c.db_column for c in job.columns]

    # Truncate staging first so reruns are idempotent
    with conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE TABLE {}").format(
            sql.Identifier(job.staging_table)
        ))

    null_set = set(job.null_values) | {""}

    rows_in_csv = 0
    # Write the normalized CSV to a tempfile rather than buffering in memory.
    # ``delete=False`` because we open it twice on Windows.
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        delete=False,
        suffix=".csv",
    )
    tmp_path = tmp.name
    try:
        writer = csv.writer(tmp, quoting=csv.QUOTE_MINIMAL)

        with csv_path.open("r", encoding=job.encoding, newline="") as src:
            if job.has_header:
                reader = csv.DictReader(src, delimiter=job.delimiter)
                # Strip BOM from the first header before validation (BUG-09).
                reader.fieldnames = _strip_bom_from_fieldnames(reader.fieldnames)
                header_set = set(reader.fieldnames or [])
                missing = [c for c in csv_columns if c not in header_set]
                if missing:
                    raise RuntimeError(
                        f"CSV is missing required columns: {missing}. "
                        f"Found: {sorted(header_set)}"
                    )
            else:
                reader = csv.DictReader(
                    src, fieldnames=csv_columns, delimiter=job.delimiter,
                )

            for row in reader:
                rows_in_csv += 1
                out_row = []
                for csv_col in csv_columns:
                    val = row.get(csv_col, "")
                    if val in null_set:
                        out_row.append("")  # COPY ... NULL '' makes this NULL
                    else:
                        out_row.append(val)
                writer.writerow(out_row)

        tmp.flush()
        tmp.close()

        copy_query = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, NULL '')").format(
            sql.Identifier(job.staging_table),
            sql.SQL(", ").join(sql.Identifier(c) for c in db_columns),
        )
        count_query = sql.SQL("SELECT COUNT(*) FROM {}").format(
            sql.Identifier(job.staging_table)
        )

        with open(tmp_path, "r", encoding="utf-8", newline="") as f, \
             conn.cursor() as cur:
            cur.copy_expert(copy_query.as_string(conn), f)
            cur.execute(count_query)
            loaded = cur.fetchone()[0]
        conn.commit()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return rows_in_csv, loaded


def promote_staging_to_target(conn, job: JobConfig) -> int:
    """Move staging rows into the final target table inside one transaction.

    Returns the number of rows in the target table after promotion.

    BUG-03: ``ON CONFLICT`` and the SET clause must use *db-side* names, not
    whatever the user wrote in the YAML's ``primary_key`` field.
    """
    cols = [c.db_column for c in job.columns]
    cols_ident = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
    target = sql.Identifier(job.target_table)
    staging = sql.Identifier(job.staging_table)
    pk_db = job.primary_key_db

    update_cols = [c for c in cols if c != pk_db]
    update_clause = sql.SQL(", ").join(
        sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c))
        for c in update_cols
    )

    with conn.cursor() as cur:
        if update_cols:
            query = sql.SQL(
                "INSERT INTO {} ({}) SELECT {} FROM {} "
                "ON CONFLICT ({}) DO UPDATE SET {}"
            ).format(
                target, cols_ident, cols_ident, staging,
                sql.Identifier(pk_db), update_clause,
            )
        else:
            query = sql.SQL(
                "INSERT INTO {} ({}) SELECT {} FROM {} "
                "ON CONFLICT ({}) DO NOTHING"
            ).format(target, cols_ident, cols_ident, staging, sql.Identifier(pk_db))
        cur.execute(query)
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(target))
        count = cur.fetchone()[0]
    conn.commit()
    return count
