"""Review of a stored upload: every row, its validation, row decisions and cell edits (M4a, #108).

Works on M3's ``source_rows``; the original is never changed. Decisions and
edits are insert-only rows (migration 0008), and the latest one wins. They are
applied by M6's staged import, not to the table imported at upload time
(product owner, 28 Oct).
"""

from __future__ import annotations

from psycopg2 import sql

from api.services.audit import current_actor, write_audit
from api.services.csv_parse import cast_value, extra_cells, ragged_row_reason, sanitize_columns
from api.tenancy import uploads_schema

MAX_PAGE = 500


class ReviewError(ValueError):
    """A request the API answers with 4xx: ``status`` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _s():
    return sql.Identifier(uploads_schema())


def _upload(cur, upload_id: int) -> dict:
    cur.execute(sql.SQL(
        "SELECT u.file_name, u.columns, u.column_types, h.cells, "
        "  (SELECT count(*) FROM {s}.source_rows r WHERE r.upload_id = u.id AND r.row_number > 0) "
        "FROM {s}.uploads u LEFT JOIN {s}.source_rows h ON h.upload_id = u.id AND h.row_number = 0 "
        "WHERE u.id = %s").format(s=_s()), (upload_id,))
    row = cur.fetchone()
    if row is None:
        raise ReviewError(404, "No such upload")
    name, columns, types, header, total = row
    columns = columns or sanitize_columns(header or [])
    # Uploads stored before 0008, or in T&E mode, have no types: every value counts as text.
    types = types if types and len(types) == len(columns) else ["text"] * len(columns)
    return {"fileName": name, "columns": columns, "types": types, "total": total}


def _validate(cells: list[str], raw: list[str], columns: list[str], types: list[str]) -> list[dict]:
    errors = []
    if extra_cells(raw, len(columns)):
        errors.append({"column": "(beyond header)", "value": extra_cells(raw, len(columns))[0],
                       "reason": ragged_row_reason(raw, len(columns))})
    for name, value, col_type in zip(columns, cells, types):
        ok, _, reason = cast_value(value, col_type)
        if not ok:
            errors.append({"column": name, "value": value, "reason": reason})
    return errors


def _latest(cur, upload_id: int, numbers: list[int]) -> tuple[dict, dict]:
    """The current decision per row and the current value per edited cell."""
    cur.execute(sql.SQL(
        "SELECT DISTINCT ON (row_number) row_number, decision, reason, actor FROM {}.row_decisions "
        "WHERE upload_id = %s AND row_number = ANY(%s) ORDER BY row_number, id DESC").format(_s()),
        (upload_id, numbers))
    decisions = {n: {"decision": d, "reason": r, "actor": a} for n, d, r, a in cur.fetchall()}
    cur.execute(sql.SQL(
        "SELECT DISTINCT ON (row_number, column_index) row_number, column_index, new_value "
        "FROM {}.cell_edits WHERE upload_id = %s AND row_number = ANY(%s) "
        "ORDER BY row_number, column_index, id DESC").format(_s()), (upload_id, numbers))
    edits: dict = {}
    for n, c, v in cur.fetchall():
        edits.setdefault(n, {})[c] = v
    return decisions, edits


def _rows(cur, upload_id: int, meta: dict, numbers: list[int] | None = None,
          offset: int = 0, limit: int = 100) -> list[dict]:
    if numbers is None:
        cur.execute(sql.SQL(
            "SELECT row_number, cells FROM {}.source_rows WHERE upload_id = %s AND row_number > 0 "
            "ORDER BY row_number OFFSET %s LIMIT %s").format(_s()), (upload_id, offset, limit))
    else:
        cur.execute(sql.SQL(
            "SELECT row_number, cells FROM {}.source_rows WHERE upload_id = %s AND row_number = ANY(%s) "
            "ORDER BY row_number").format(_s()), (upload_id, numbers))
    source = cur.fetchall()
    decisions, edits = _latest(cur, upload_id, [n for n, _ in source])
    width = len(meta["columns"])
    out = []
    for n, raw in source:
        original = (list(raw) + [""] * width)[:width]
        current = [edits.get(n, {}).get(c, v) for c, v in enumerate(original)]
        decision = decisions.get(n)
        out.append({
            "rowNumber": n, "original": original, "current": current,
            "editedColumns": sorted(edits.get(n, {})),
            "decision": decision["decision"] if decision else "include",
            "decisionReason": decision["reason"] if decision else None,
            "errors": _validate(current, raw, meta["columns"], meta["types"]),
        })
    return out


def page(cur, upload_id: int, offset: int, limit: int) -> dict:
    meta = _upload(cur, upload_id)
    offset, limit = max(0, offset), max(1, min(limit, MAX_PAGE))
    cur.execute(sql.SQL(
        "SELECT (SELECT count(*) FROM (SELECT DISTINCT ON (row_number) decision FROM {s}.row_decisions "
        "        WHERE upload_id = %s ORDER BY row_number, id DESC) d WHERE decision = 'exclude'), "
        "       (SELECT count(DISTINCT row_number) FROM {s}.cell_edits WHERE upload_id = %s)").format(s=_s()),
        (upload_id, upload_id))
    excluded, edited = cur.fetchone()
    return {**meta, "offset": offset, "limit": limit, "excludedRows": excluded, "editedRows": edited,
            "rows": _rows(cur, upload_id, meta, offset=offset, limit=limit)}


def _check_row(meta: dict, row_number: int) -> None:
    if not 1 <= row_number <= meta["total"]:
        raise ReviewError(404, f"Row {row_number} doesn't exist; this upload has {meta['total']} rows")


def _reason(reason: str) -> str:
    if not (reason or "").strip():
        raise ReviewError(422, "A reason is required")
    return reason.strip()


def decide(cur, upload_id: int, row_number: int, decision: str, reason: str) -> dict:
    """Include or exclude one row. The caller commits."""
    meta = _upload(cur, upload_id)
    _check_row(meta, row_number)
    if decision not in ("include", "exclude"):
        raise ReviewError(422, "decision must be 'include' or 'exclude'")
    reason = _reason(reason)
    [before] = _rows(cur, upload_id, meta, numbers=[row_number])
    cur.execute(sql.SQL("INSERT INTO {}.row_decisions (upload_id, row_number, decision, reason, actor) "
                        "VALUES (%s, %s, %s, %s, %s)").format(_s()),
                (upload_id, row_number, decision, reason, current_actor()))
    write_audit(cur, "row_decision", None, meta["fileName"], None, None,
                before={"upload": upload_id, "row": row_number, "decision": before["decision"]},
                after={"upload": upload_id, "row": row_number, "decision": decision, "reason": reason})
    [after] = _rows(cur, upload_id, meta, numbers=[row_number])
    return after


def edit(cur, upload_id: int, row_number: int, column: str, value: str, reason: str) -> dict:
    """Set one cell's value as a new version. ``column`` is a name or a 0-based index. The caller commits."""
    meta = _upload(cur, upload_id)
    _check_row(meta, row_number)
    names = meta["columns"]
    index = int(column) if column.isdigit() else (names.index(column) if column in names else -1)
    if not 0 <= index < len(names):
        raise ReviewError(404, f"No column {column!r}")
    reason = _reason(reason)
    [before] = _rows(cur, upload_id, meta, numbers=[row_number])
    old = before["current"][index]
    if value == old:
        raise ReviewError(422, "The new value is the same as the current one")
    cur.execute(sql.SQL("INSERT INTO {}.cell_edits (upload_id, row_number, column_index, old_value, new_value, "
                        "reason, actor) VALUES (%s, %s, %s, %s, %s, %s, %s)").format(_s()),
                (upload_id, row_number, index, old, value, reason, current_actor()))
    cell = {"upload": upload_id, "row": row_number, "column": names[index]}
    write_audit(cur, "cell_edit", None, meta["fileName"], None, None,
                before={**cell, "value": old}, after={**cell, "value": value, "reason": reason})
    [after] = _rows(cur, upload_id, meta, numbers=[row_number])
    return after


def history(cur, upload_id: int, row_number: int) -> list[dict]:
    """Every decision and edit on one row, oldest first."""
    meta = _upload(cur, upload_id)
    _check_row(meta, row_number)
    cur.execute(sql.SQL(
        "SELECT 'decision', decided_at, actor, reason, decision, NULL::int, NULL, NULL FROM {s}.row_decisions "
        "  WHERE upload_id = %s AND row_number = %s "
        "UNION ALL SELECT 'edit', edited_at, actor, reason, NULL, column_index, old_value, new_value "
        "  FROM {s}.cell_edits WHERE upload_id = %s AND row_number = %s ORDER BY 2").format(s=_s()),
        (upload_id, row_number, upload_id, row_number))
    out = []
    for kind, at, actor, reason, decision, index, old, new in cur.fetchall():
        entry = {"kind": kind, "at": at.isoformat(), "actor": actor, "reason": reason}
        if kind == "decision":
            entry["decision"] = decision
        else:
            entry.update(column=meta["columns"][index], oldValue=old, newValue=new)
        out.append(entry)
    return out
