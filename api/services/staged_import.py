"""Approval and staged, transactional import (M6, #110; BR-32, BR-33, BR-34; ADR-0002).

The flow, for dynamic-mode uploads:

1. ``stage``: store the original and its parsed rows (insert-only). Nothing is imported.
2. Review (M4): row decisions and cell edits, recorded as rows.
3. ``submit``, then ``decide_approval``: a reviewer approves or rejects. Approval records which
   decisions and edits were current (``decisions_upto``, ``edits_upto``), so the import applies
   exactly what was approved. A rejected upload can be reviewed again and resubmitted.
4. ``import_upload``: one transaction takes the approved rows, COPYs them into a temporary
   staging table, promotes them into ``csv_<slug>_v<n>`` with lineage columns, registers the file,
   writes the ``imports`` record and the audit event, and commits. Any failure rolls all of it back,
   so there are no partial imports (decision 4) and no import without its audit row.

State is derived from the insert-only tables (``uploads``, ``submissions``, ``approvals``,
``imports``): staged, submitted, approved, rejected, imported. An upload made through the older
``/api/csv/upload`` has no workflow and reads as ``legacy``.

Deviation from ADR-0002: rows are validated in Python with ``cast_value`` before COPY, not in SQL
after it. That cast is the one contract shared with the loaders and the frontend, and a row that
fails it stops the approval, so nothing invalid reaches staging.
Not covered: T&E mode. T&E uploads keep using ``/api/csv/upload`` and its row-level isolation.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging

import psycopg2.errors
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.services.audit import current_actor, write_audit
from api.services.csv_parse import (
    ALLOWED_TYPES,
    apply_header_mapping,
    cast_value,
    extra_cells,
    parse_csv,
    ragged_row_reason,
    sanitize_columns,
    valid_identifier,
)
from api.services.dynamic_loader import _TYPE_SQL, _earlier_version_matches, _schema_diff, dataset_slug
from api.services.originals import store_upload
from api.tenancy import uploads_schema

logger = logging.getLogger(__name__)

IMPORT_STATEMENT_TIMEOUT_MS = 120_000  # ADR-0002: one open transaction needs a bound


class WorkflowError(Exception):
    """A request the API answers with 4xx: ``status`` is the HTTP code; ``extra`` goes in the body."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _checkpoint(step: str) -> None:
    """A seam for failure-injection tests: they patch this to raise at a named step of the import."""


def _s():
    return sql.Identifier(uploads_schema())


def _row_hash(cells: list[str]) -> str:
    # Same scheme as dynamic_loader (#178): JSON, so no cell content can make two rows collide.
    return "v2:" + hashlib.sha256(json.dumps(cells, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- staging ---------------------------------------------------------------------------------

def prepare(content: str, types: list[str] | None, header_mapping: list[dict] | None):
    """Parse and check a CSV the way the dynamic loader does. Returns (rows, columns, types) or raises.

    ponytail: duplicates the loader's structural checks; the loader's own path goes away once
    the frontend uses this flow (ADR-0002), so they aren't shared.
    """
    rows = parse_csv(content)
    if not rows:
        raise WorkflowError(422, "This CSV is empty — no header row and no data rows were detected.", reason="empty")
    if len(rows) == 1:
        raise WorkflowError(422, "This CSV has a header row but no data rows. Add at least one data row.",
                            reason="header_only")
    if all((c or "").strip() == "" for c in rows[0]):
        raise WorkflowError(422, "This CSV's first row is blank, so no column headers were detected.",
                            reason="no_columns")
    mapped, error = apply_header_mapping(rows[0], header_mapping)
    if error:
        raise WorkflowError(422, error, reason="invalid_header_mapping")
    if len(rows) - 1 > settings.MAX_ROWS:
        raise WorkflowError(422, f"CSV has {len(rows) - 1} data rows; the API accepts at most {settings.MAX_ROWS}.",
                            reason="too_many_rows")
    columns = sanitize_columns(mapped)
    if not columns:
        raise WorkflowError(422, "No columns found in the CSV header.", reason="no_columns")
    if len(set(columns)) != len(columns):
        dupe = next(c for i, c in enumerate(columns) if columns.index(c) != i)
        raise WorkflowError(422, f'Duplicate sanitized column name "{dupe}" — rename headers in the CSV.',
                            reason="duplicate_columns")
    if any(not valid_identifier(c) for c in columns):
        raise WorkflowError(422, "Column headers could not be converted to safe identifiers.", reason="bad_columns")
    if types is not None and len(types) != len(columns):
        raise WorkflowError(422, f"Provided {len(types)} column types but the CSV has {len(columns)} columns.",
                            reason="bad_types")
    col_types = types if types else ["text"] * len(columns)
    if any(t not in ALLOWED_TYPES for t in col_types):
        raise WorkflowError(422, "Unsupported column type provided.", reason="bad_types")
    return rows, columns, col_types


def stage(cur, file_name: str, content: str, types: list[str] | None, header_mapping: list[dict] | None,
          original: bytes | None, types_confirmed: bool = False) -> dict:
    """Store an upload for review without importing it. Every attempt is recorded (BR-23).

    Returns a result dict whose ``status`` is ``staged``, ``duplicate_file`` or ``invalid_structure``,
    always with ``uploadId``. The caller commits.
    """
    sha = hashlib.sha256(original if original is not None else content.encode("utf-8")).hexdigest()
    try:
        rows, columns, col_types = prepare(content, types, header_mapping)
    except WorkflowError as exc:
        result = {"status": "invalid_structure", "message": str(exc), **exc.extra}
        return {**result, "uploadId": str(store_upload(cur, file_name, content, "dynamic", result, original=original))}

    cur.execute(sql.SQL("SELECT file_name, table_name, row_count FROM {}.csv_files WHERE file_hash = %s")
                .format(_s()), (sha,))
    match = cur.fetchone()
    if match:
        result = {"status": "duplicate_file", "reason": "content", "existingFileName": match[0],
                  "tableName": match[1], "existingRowCount": match[2] or 0}
        return {**result, "uploadId": str(store_upload(cur, file_name, content, "dynamic", result, original=original))}

    # BR-29: flag rows already in an earlier version of this dataset, so the reviewer sees them before approving.
    dataset = dataset_slug(file_name)
    cur.execute(sql.SQL("SELECT id, file_name, table_name, version FROM {}.csv_files WHERE dataset = %s "
                        "ORDER BY version DESC").format(_s()), (dataset,))
    priors = cur.fetchall()
    flags: list[dict] = []
    if priors:
        width, seen, hashes, numbers = len(columns), set(), [], []
        for n, raw in enumerate(rows[1:], start=1):
            if extra_cells(raw, width):
                continue
            h = _row_hash([raw[c] if c < len(raw) else "" for c in range(width)])
            if h not in seen:
                seen.add(h)
                hashes.append(h)
                numbers.append(n)
        flags = _earlier_version_matches(cur, uploads_schema(), priors, hashes, numbers)

    # #195: the registry says whether a person confirmed the types; the import records it.
    provenance = "user_confirmed" if (types and types_confirmed) else "inferred_unconfirmed"
    result = {"status": "staged", "totalRows": len(rows) - 1, "columns": columns, "types": col_types,
              "typesProvenance": provenance}
    upload_id = store_upload(cur, file_name, content, "dynamic", result, original=original, flags=flags)
    return {**result, "uploadId": str(upload_id), "state": "staged", "dataset": dataset,
            "duplicateRowsAcrossUploads": len(flags),
            "crossUploadDuplicates": flags[:settings.MAX_ROW_ERRORS_REPORTED]}


# -- state -----------------------------------------------------------------------------------

def state_columns() -> sql.Composed:
    """Select-list part for an ``uploads u`` query that also has ``state_join()``: has_import, sub_id, decision."""
    return sql.SQL("EXISTS (SELECT 1 FROM {s}.imports i WHERE i.upload_id = u.id) AS has_import, "
                   "w.sub_id, w.decision").format(s=_s())


def state_join() -> sql.Composed:
    """The latest submission of ``u`` and its approval decision, if any."""
    return sql.SQL("LEFT JOIN LATERAL (SELECT sb.id AS sub_id, a.decision FROM {s}.submissions sb "
                   "LEFT JOIN {s}.approvals a ON a.submission_id = sb.id WHERE sb.upload_id = u.id "
                   "ORDER BY sb.id DESC LIMIT 1) w ON true").format(s=_s())


def derive_state(status: str, has_import: bool, sub_id: int | None, decision: str | None) -> str:
    if has_import:
        return "imported"
    if sub_id is None:
        return "staged" if status == "staged" else "legacy"
    if decision is None:
        return "submitted"
    return "approved" if decision == "approve" else "rejected"


def state_of(cur, upload_id: int) -> dict | None:
    """The upload's workflow state with its latest submission, approval and import. None if there is no such upload."""
    cur.execute(sql.SQL("SELECT u.status, u.uploader, u.file_name, u.sha256, u.types_provenance, {cols} "
                        "FROM {s}.uploads u {join} WHERE u.id = %s")
                .format(cols=state_columns(), s=_s(), join=state_join()), (upload_id,))
    row = cur.fetchone()
    if row is None:
        return None
    status, uploader, file_name, sha, provenance, has_import, sub_id, decision = row
    out = {"uploadId": str(upload_id), "state": derive_state(status, has_import, sub_id, decision),
           "fileName": file_name, "uploader": uploader, "sha256": sha, "typesProvenance": provenance,
           "submission": None, "approval": None, "import": None}
    if sub_id is not None:
        cur.execute(sql.SQL("SELECT submitter, note, submitted_at FROM {}.submissions WHERE id = %s").format(_s()),
                    (sub_id,))
        who, note, at = cur.fetchone()
        out["submission"] = {"id": str(sub_id), "submitter": who, "note": note, "at": at.isoformat()}
        cur.execute(sql.SQL("SELECT id, decision, reason, approver, decisions_upto, edits_upto, decided_at "
                            "FROM {}.approvals WHERE submission_id = %s").format(_s()), (sub_id,))
        a = cur.fetchone()
        if a:
            out["approval"] = {"id": str(a[0]), "decision": a[1], "reason": a[2], "approver": a[3],
                               "decisionsUpto": a[4], "editsUpto": a[5], "at": a[6].isoformat()}
    if has_import:
        cur.execute(sql.SQL("SELECT id, idempotency_key, rows_in, rows_excluded, rows_edited, rows_duplicate, "
                            "rows_imported, csv_file_id, table_name, importer, imported_at FROM {}.imports "
                            "WHERE upload_id = %s").format(_s()), (upload_id,))
        i = cur.fetchone()
        out["import"] = {"id": str(i[0]), "idempotencyKey": i[1], "reconciliation": _reconciliation(*i[2:7]),
                         "fileId": str(i[7]), "tableName": i[8], "importer": i[9], "at": i[10].isoformat()}
    return out


def _reconciliation(rows_in: int, excluded: int, edited: int, duplicate: int, imported: int) -> dict:
    return {"rowsIn": rows_in, "excluded": excluded, "edited": edited, "duplicate": duplicate, "imported": imported}


def history(cur, upload_id: int) -> list[dict]:
    """Every submission, decision and import on an upload, oldest first."""
    cur.execute(sql.SQL(
        "SELECT 'submitted', submitted_at, submitter, note FROM {s}.submissions WHERE upload_id = %s "
        "UNION ALL SELECT CASE decision WHEN 'approve' THEN 'approved' ELSE 'rejected' END, decided_at, approver, reason "
        "FROM {s}.approvals WHERE upload_id = %s "
        "UNION ALL SELECT 'imported', imported_at, importer, NULL FROM {s}.imports WHERE upload_id = %s "
        "ORDER BY 2").format(s=_s()), (upload_id,) * 3)
    return [{"event": e, "at": at.isoformat(), "actor": who, "note": note} for e, at, who, note in cur.fetchall()]


# -- submit and decide -----------------------------------------------------------------------

def _require(cur, upload_id: int) -> dict:
    st = state_of(cur, upload_id)
    if st is None:
        raise WorkflowError(404, "No such upload")
    return st


def submit(cur, upload_id: int, note: str | None) -> dict:
    """Submit a staged or rejected upload for approval. The caller commits."""
    st = _require(cur, upload_id)
    if st["state"] == "legacy":
        raise WorkflowError(409, "This upload was imported directly and has no approval workflow", state="legacy")
    if st["state"] not in ("staged", "rejected"):
        raise WorkflowError(409, f"This upload is already {st['state']}", state=st["state"])
    cur.execute(sql.SQL("INSERT INTO {}.submissions (upload_id, submitter, note) VALUES (%s, %s, %s) RETURNING id")
                .format(_s()), (upload_id, current_actor(), (note or "").strip() or None))
    sub_id = cur.fetchone()[0]
    write_audit(cur, "submit", None, st["fileName"], None, "dynamic",
                before={"upload": upload_id, "state": st["state"]},
                after={"upload": upload_id, "submission": sub_id, "note": (note or "").strip() or None})
    return state_of(cur, upload_id)


def _self_approval_allowed(cur, session: dict) -> bool:
    cur.execute(sql.SQL("SELECT allow_self_approval FROM {}.tenants WHERE slug = %s")
                .format(sql.Identifier(settings.CONTROL_SCHEMA)), (session["tenant"],))
    row = cur.fetchone()
    return bool(row and row[0])


def decide_approval(cur, upload_id: int, decision: str, reason: str | None, session: dict | None) -> dict:
    """Approve or reject the pending submission. The caller commits.

    Approving needs every non-excluded row to pass validation (otherwise the import couldn't run),
    and, for a signed-in member, that they didn't upload or submit it, unless the tenant allows it
    (decision 5). A request with no session has no identity to compare, so it isn't checked.
    """
    st = _require(cur, upload_id)
    if st["state"] != "submitted":
        raise WorkflowError(409, f"This upload is {st['state']}; only a submitted upload can be approved or rejected",
                            state=st["state"])
    if decision not in ("approve", "reject"):
        raise WorkflowError(422, "decision must be 'approve' or 'reject'")
    reason = (reason or "").strip() or None
    if decision == "reject" and not reason:
        raise WorkflowError(422, "A reason is required to reject")
    if decision == "approve" and session is not None and session["username"] in (st["uploader"], st["submission"]["submitter"]):
        if not _self_approval_allowed(cur, session):
            raise WorkflowError(403, "You uploaded or submitted this data, so another member must approve it. "
                                     "A tenant with a single user can allow self-approval.")
    cur.execute(sql.SQL("SELECT COALESCE(max(id), 0) FROM {}.row_decisions WHERE upload_id = %s").format(_s()),
                (upload_id,))
    decisions_upto = cur.fetchone()[0]
    cur.execute(sql.SQL("SELECT COALESCE(max(id), 0) FROM {}.cell_edits WHERE upload_id = %s").format(_s()),
                (upload_id,))
    edits_upto = cur.fetchone()[0]
    if decision == "approve":
        plan = effective_rows(cur, upload_id, decisions_upto, edits_upto)
        if plan["invalid"]:
            raise WorkflowError(422, f"{plan['invalid']} row(s) still fail validation. Exclude or edit them, then approve.",
                                invalidRows=plan["invalid"], rowErrors=plan["errors"])
    cur.execute(sql.SQL("INSERT INTO {}.approvals (submission_id, upload_id, decision, reason, approver, "
                        "decisions_upto, edits_upto) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id").format(_s()),
                (int(st["submission"]["id"]), upload_id, decision, reason, current_actor(), decisions_upto, edits_upto))
    approval_id = cur.fetchone()[0]
    write_audit(cur, decision, None, st["fileName"], None, "dynamic",
                before={"upload": upload_id, "state": "submitted"},
                after={"upload": upload_id, "submission": int(st["submission"]["id"]), "approval": approval_id,
                       "decision": decision, "reason": reason})
    return state_of(cur, upload_id)


# -- the rows an import would load -----------------------------------------------------------

def effective_rows(cur, upload_id: int, decisions_upto: int, edits_upto: int) -> dict:
    """What an import of this upload loads, as of the given decision and edit ids (BR-33, BR-34).

    Applies the newest decision and edit per row up to those ids, drops excluded rows, validates the
    rest and drops rows identical to an earlier one. Returns the counts that reconcile
    (rows_in = excluded + duplicate + len(valid) + invalid), ``valid`` as (row_number, values, hash),
    and ``errors`` (capped) for rows that fail, counted in ``invalid``.
    """
    cur.execute(sql.SQL("SELECT columns, column_types FROM {}.uploads WHERE id = %s").format(_s()), (upload_id,))
    columns, types = cur.fetchone()
    cur.execute(sql.SQL("SELECT DISTINCT ON (row_number) row_number, decision FROM {}.row_decisions "
                        "WHERE upload_id = %s AND id <= %s ORDER BY row_number, id DESC").format(_s()),
                (upload_id, decisions_upto))
    excluded = {n for n, d in cur.fetchall() if d == "exclude"}
    cur.execute(sql.SQL("SELECT DISTINCT ON (row_number, column_index) row_number, column_index, new_value "
                        "FROM {}.cell_edits WHERE upload_id = %s AND id <= %s "
                        "ORDER BY row_number, column_index, id DESC").format(_s()), (upload_id, edits_upto))
    edits: dict[int, dict[int, str]] = {}
    for n, c, v in cur.fetchall():
        edits.setdefault(n, {})[c] = v
    cur.execute(sql.SQL("SELECT row_number, cells FROM {}.source_rows WHERE upload_id = %s AND row_number > 0 "
                        "ORDER BY row_number").format(_s()), (upload_id,))
    width = len(columns)
    out = {"rowsIn": 0, "excluded": 0, "edited": 0, "duplicate": 0, "invalid": 0, "valid": [], "errors": [],
           "columns": columns, "types": types}
    seen: set[str] = set()
    for n, raw in cur.fetchall():
        out["rowsIn"] += 1
        if n in excluded:
            out["excluded"] += 1
            continue
        changed = edits.get(n, {})
        if changed:
            out["edited"] += 1
        cells = [changed[c] if c in changed else (raw[c] if c < len(raw) else "") for c in range(width)]
        error = None
        if extra_cells(raw, width):
            error = {"column": "(beyond header)", "value": extra_cells(raw, width)[0],
                     "reason": ragged_row_reason(raw, width)}
        values: list = []
        for c in range(width):
            if error:
                break
            ok, val, reason = cast_value(cells[c], types[c])
            if not ok:
                error = {"column": columns[c], "value": cells[c], "reason": reason}
            values.append(val)
        if error:
            out["invalid"] += 1
            if len(out["errors"]) < settings.MAX_ROW_ERRORS_REPORTED:
                out["errors"].append({"rowNumber": n, **error})
            continue
        h = _row_hash(cells)
        if h in seen:
            out["duplicate"] += 1
            continue
        seen.add(h)
        out["valid"].append((n, values, h))
    return out


# -- the import ------------------------------------------------------------------------------

def _copy_text(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _copy_data(rows: list[tuple]) -> io.StringIO:
    """CSV text for COPY ... NULL '\\N'. Every value is quoted, so a text value of \\N stays text."""
    buf = io.StringIO()
    for row in rows:
        buf.write(",".join("\\N" if v is None else '"' + _copy_text(v).replace('"', '""') + '"' for v in row))
        buf.write("\n")
    buf.seek(0)
    return buf


def _replay(st: dict) -> dict:
    i = st["import"]
    return {"status": "ok", "replayed": True, "importId": i["id"], "fileId": i["fileId"], "tableName": i["tableName"],
            "reconciliation": i["reconciliation"]}


def import_upload(upload_id: int, key: str, session: dict | None) -> dict:
    """Import an approved upload in one transaction, or change nothing (ADR-0002).

    ``key`` is the client's Idempotency-Key. Repeating a successful import with the same key returns
    the original result; another key for an already-imported upload is a 409. A failed import leaves
    no table, registry row, import record or audit row, so retrying with the same key is safe.
    """
    key = (key or "").strip()
    if not key or len(key) > 255:
        raise WorkflowError(422, "Idempotency-Key header is required (1 to 255 characters)")
    schema = uploads_schema()
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(IMPORT_STATEMENT_TIMEOUT_MS),))
            # One import per upload at a time; a concurrent retry waits, then sees the committed result.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{schema}.import.{upload_id}",))
            st = _require(cur, upload_id)
            if st["import"]:
                if st["import"]["idempotencyKey"] == key:
                    return _replay(st)
                raise WorkflowError(409, "This upload has already been imported", state="imported",
                                    importId=st["import"]["id"])
            if st["state"] != "approved":
                raise WorkflowError(409, f"This upload is {st['state']}; only an approved upload can be imported",
                                    state=st["state"])
            approval = st["approval"]
            plan = effective_rows(cur, upload_id, approval["decisionsUpto"], approval["editsUpto"])
            if plan["invalid"]:  # approval checked this; only a bug or manual DB change gets here
                raise WorkflowError(422, f"{plan['invalid']} approved row(s) fail validation", invalidRows=plan["invalid"],
                                    rowErrors=plan["errors"])
            columns, col_types, valid = plan["columns"], plan["types"], plan["valid"]
            counts = _reconciliation(plan["rowsIn"], plan["excluded"], plan["edited"], plan["duplicate"], len(valid))

            # Same per-dataset lock as the loader, so versions are never handed out twice (M5).
            dataset = dataset_slug(st["fileName"])
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{schema}.{dataset}",))
            cur.execute(sql.SQL("SELECT id, file_name, table_name, version FROM {}.csv_files WHERE dataset = %s "
                                "ORDER BY version DESC").format(_s()), (dataset,))
            priors = cur.fetchall()
            version = priors[0][3] + 1 if priors else 1
            table_name = f"csv_{dataset}_v{version}"
            schema_check = _schema_diff(cur, schema, priors[0][2], columns, col_types) if priors else None

            try:
                cur.execute(sql.SQL(
                    "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names, "
                    "total_rows, duplicate_rows_skipped, failed_rows, types_provenance, dataset, version) "
                    "VALUES (%s, %s, %s, 'dynamic', %s, %s, %s, %s, 0, %s, %s, %s) RETURNING id").format(_s()),
                    (st["fileName"], st["sha256"], table_name, len(valid), columns, counts["rowsIn"],
                     counts["duplicate"], st["typesProvenance"] or "inferred_unconfirmed", dataset, version))
            except psycopg2.errors.UniqueViolation:
                conn.rollback()  # the same bytes were imported meanwhile (exact-file dedup, BR-28)
                raise WorkflowError(409, "These exact file contents were already imported", state="duplicate_file") from None
            file_id = cur.fetchone()[0]
            cur.execute(sql.SQL(
                "INSERT INTO {}.imports (upload_id, approval_id, idempotency_key, rows_in, rows_excluded, "
                "rows_edited, rows_duplicate, rows_imported, csv_file_id, table_name, importer) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id").format(_s()),
                (upload_id, int(approval["id"]), key, counts["rowsIn"], counts["excluded"], counts["edited"],
                 counts["duplicate"], len(valid), file_id, table_name, current_actor()))
            import_id = cur.fetchone()[0]
            _checkpoint("registered")

            target, staging = sql.Identifier(schema, table_name), sql.Identifier(f"_stg_{import_id}")
            col_defs = sql.SQL(", ").join(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(_TYPE_SQL[t]))
                                          for c, t in zip(columns, col_types))
            cols = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
            # Plain CREATE: a name clash must fail the import, not append to another table.
            cur.execute(sql.SQL("CREATE TABLE {} (_id BIGSERIAL PRIMARY KEY, {}, _row_hash TEXT NOT NULL UNIQUE, "
                                "_created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                                "_source_row_id INTEGER NOT NULL, _import_id BIGINT NOT NULL)")
                        .format(target, col_defs))
            cur.execute(sql.SQL("CREATE TEMP TABLE {} (_source_row_id INTEGER, {}, _row_hash TEXT) ON COMMIT DROP")
                        .format(staging, col_defs))
            try:
                cur.copy_expert(
                    sql.SQL("COPY {} (_source_row_id, {}, _row_hash) FROM STDIN WITH (FORMAT csv, NULL '\\N')")
                    .format(staging, cols).as_string(cur),
                    _copy_data([(n, *values, h) for n, values, h in valid]))
                _checkpoint("staged")
                cur.execute(sql.SQL("INSERT INTO {t} ({c}, _row_hash, _source_row_id, _import_id) "
                                    "SELECT {c}, _row_hash, _source_row_id, %s FROM {s} ORDER BY _source_row_id")
                            .format(t=target, c=cols, s=staging), (import_id,))
            except psycopg2.errors.DataError as exc:
                conn.rollback()
                raise WorkflowError(422, "The database rejected the data: " + str(exc).splitlines()[0]) from None
            if cur.rowcount != len(valid):
                raise RuntimeError(f"Import {import_id} promoted {cur.rowcount} rows; expected {len(valid)}")
            _checkpoint("promoted")
            write_audit(cur, "import", file_id, st["fileName"], table_name, "dynamic",
                        before={"upload": upload_id, "state": "approved"},
                        after={"upload": upload_id, "import": import_id, "approval": int(approval["id"]),
                               "table": table_name, "reconciliation": counts})
        conn.commit()
    return {"status": "ok", "replayed": False, "importId": str(import_id), "fileId": str(file_id),
            "tableName": table_name, "dataset": dataset, "version": version, "reconciliation": counts,
            "schemaCheck": schema_check}
