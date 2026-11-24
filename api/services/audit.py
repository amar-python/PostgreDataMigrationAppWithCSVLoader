"""Shared writer for ``csv_uploads.audit_log`` (O-04).

Before this module the audit table had exactly one writer — ``delete_file`` in
``api/routers/csv_routes.py`` — so the log recorded destructions but not
creations. An auditor reading it could see that a table had been deleted and
never see who loaded it. Every mutating action now writes a row through here.

Every writer uses the caller's cursor (``write_audit``), so the audit row commits in the same
transaction as the change it describes. ``POST /api/csv/upload`` passes a hook to the loaders that
writes the upload audit row on the load's cursor just before the load commits (#288, BR-45, BR-52);
the approval flow (M6, api/services/staged_import.py) does the same in its own transaction. The
former ``record_audit``, which wrote after the load had committed and swallowed its own errors, is
retired (ADR-0002).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg2 import sql

from api.tenancy import uploads_schema

logger = logging.getLogger(__name__)

# Actions the log is allowed to record. A typo becomes a loud failure here rather
# than an unqueryable string in the table.
VALID_ACTIONS = frozenset({"upload", "delete", "password_reset", "row_decision", "cell_edit",
                           "submit", "approve", "reject", "import"})

# Who is acting (M3a, #107). tenant_scope sets it per request: the signed-in
# username, or "anonymous" under the local-dev anonymous opt-in (#298; the shared
# key that used to audit as "api_key" was retired).
_actor: ContextVar[str | None] = ContextVar("audit_actor", default=None)


def current_actor() -> str | None:
    return _actor.get()


@contextmanager
def acting_as(actor: str):
    token = _actor.set(actor)
    try:
        yield
    finally:
        _actor.reset(token)


def write_audit(cur, action: str, file_id: int | None, file_name: str | None,
                table_name: str | None, mode: str | None,
                before: dict | None = None, after: dict | None = None) -> None:
    """Insert one audit row using the caller's cursor.

    Use this when you already hold a transaction and want the audit row to
    commit atomically with the change it describes. The caller commits.
    The table's trigger adds the tenant schema and the hash chain (0006).
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown audit action {action!r}; expected one of {sorted(VALID_ACTIONS)}")
    cur.execute(
        sql.SQL(
            "INSERT INTO {}.audit_log "
            "(action, file_id, file_name, table_name, mode, actor, before_value, after_value) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier(uploads_schema())),
        (action, file_id, file_name, table_name, mode, _actor.get(),
         None if before is None else json.dumps(before),
         None if after is None else json.dumps(after)),
    )


def verify_chain(cur) -> dict:
    """Recompute the audit hash chain (M3a). Returns the row count and the
    first row whose link or hash doesn't match, or None if the chain is intact."""
    schema = sql.Identifier(uploads_schema())
    cur.execute(sql.SQL(
        "SELECT count(*), min(id) FILTER (WHERE prev_hash IS DISTINCT FROM expected_prev "
        "  OR row_hash IS DISTINCT FROM {s}.audit_row_hash(prev_hash, r)) "
        "FROM (SELECT a AS r, a.id, a.prev_hash, a.row_hash, "
        "             lag(a.row_hash) OVER (ORDER BY a.id) AS expected_prev "
        "      FROM {s}.audit_log a) t"
    ).format(s=schema))
    rows, first_bad = cur.fetchone()
    return {"rows": rows, "intact": first_bad is None, "firstBadId": first_bad}


def coerce_file_id(raw: str | int | None) -> int | None:
    """Best-effort conversion of a loader's ``fileId`` to the BIGINT column type.

    The loaders return it as a string. A malformed value must not cost us the
    whole audit row, so this yields None and lets the row record the action with
    a null id rather than raising.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Unparseable fileId %r in audit call; recording NULL", raw)
        return None
