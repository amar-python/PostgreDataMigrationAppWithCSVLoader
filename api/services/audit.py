"""Shared writer for ``csv_uploads.audit_log`` (O-04).

Before this module the audit table had exactly one writer — ``delete_file`` in
``api/routers/csv_routes.py`` — so the log recorded destructions but not
creations. An auditor reading it could see that a table had been deleted and
never see who loaded it. Every mutating action now writes a row through here.

Known limitation (deliberate, documented)
-----------------------------------------
The loaders in ``api/services/{dynamic,te}_loader.py`` own and commit their own
transactions, so the audit row for an upload is written *after* the load has
already committed rather than inside the same transaction. A crash in the narrow
window between the two leaves a load with no audit row.

Because of that ordering, a failure to write the audit row must NOT fail the
request: the data is already in the database, and reporting failure for a load
that actually succeeded would be worse than a missing log line. The failure is
logged at ERROR so it is alertable.

Closing that window properly means threading the caller's connection into the
loaders so the audit INSERT joins their transaction — worth doing, but it changes
the loader signatures and is tracked separately rather than smuggled in here.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg2 import sql

from api.tenancy import uploads_schema
from api.db import Conn

logger = logging.getLogger(__name__)

# Actions the log is allowed to record. A typo becomes a loud failure here rather
# than an unqueryable string in the table.
VALID_ACTIONS = frozenset({"upload", "delete", "password_reset"})

# Who is acting (M3a, #107). tenant_scope sets it per request: the signed-in
# username, or "api_key" for a request made with the shared key.
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


def record_audit(action: str, file_id: int | None, file_name: str | None,
                 table_name: str | None, mode: str | None) -> bool:
    """Insert one audit row in its own transaction. Never raises.

    Returns True when the row was written. Used on the upload path, where the
    load has already committed — see the module docstring for why a failure here
    is logged rather than propagated.
    """
    try:
        with Conn() as conn:
            with conn.cursor() as cur:
                write_audit(cur, action, file_id, file_name, table_name, mode)
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — audit must not break a committed load
        logger.error(
            "Failed to write audit row (action=%s file_id=%s file_name=%r): %s",
            action, file_id, file_name, exc,
        )
        return False


def coerce_file_id(raw: object) -> int | None:
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
