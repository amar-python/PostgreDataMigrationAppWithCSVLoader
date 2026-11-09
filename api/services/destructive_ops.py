"""Centralised authorisation for destructive database operations (#175, #170).

Every code path that drops a user-data table must go through one of these
functions.  This prevents the auth bypass where upload-with-overwrite or
T&E mode-switch silently dropped tables without checking delete permission.
"""

from __future__ import annotations

from fastapi import HTTPException
from psycopg2 import sql

from api.auth import PERMISSIONS


def authorized_drop_table(cur, session: dict | None, schema: str, table_name: str) -> None:
    """Drop a table only if the caller holds delete_file permission.

    ``session`` is ``None`` for API-key (non-session) requests, which are
    allowed through (they have full access until per-key roles exist).
    Raises HTTP 403 if the session's role lacks ``delete_file``.
    """
    _require_delete(session)
    cur.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table_name)
        )
    )


def safe_cleanup_prior(cur, session: dict | None, schema: str,
                       table_name: str, mode: str) -> None:
    """Drop a prior dynamic-mode table during overwrite, with auth check.

    Only drops when the prior entry is dynamic mode and the table name starts
    with ``csv_`` (T&E-mode entries point at shared tables that must not be
    dropped here).
    """
    _require_delete(session)
    if mode == "dynamic" and table_name.startswith("csv_"):
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table_name)
            )
        )


def _require_delete(session: dict | None) -> None:
    """Raise 403 if the session's role cannot delete files."""
    if session is None:
        return
    roles = PERMISSIONS["delete_file"]
    if session["role"] not in roles:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{session['role']}' may not delete or overwrite files",
        )
