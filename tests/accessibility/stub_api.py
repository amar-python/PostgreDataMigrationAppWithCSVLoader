"""The API as the browser sees it during an accessibility scan (#168).

The scans check the *frontend's* markup, so they need no database and no API process:
every ``/api/**`` request is answered here with a fixed response, and a signed-in session
is planted in sessionStorage. Same inputs, same pages, same result on every run, and a
backend-only pull request cannot change what is scanned.

The payloads must satisfy the frontend's zod schemas (csv-table-hub-main/src/lib/
csv.functions.ts); a schema mismatch shows up as a page that shows an error instead of the
content, which the scenarios' content checks catch.

No Playwright import here: this module only describes data and a request handler.
"""
from __future__ import annotations

import json
from urllib.parse import quote
from typing import Any, Callable

SESSION = {"token": "a11y-scan-token", "expiresAt": "2099-01-01T00:00:00Z",
           "username": "ada", "tenant": "acme", "role": "admin"}

FILES = [{
    "id": "1", "file_name": "customers.csv", "table_name": "csv_customers", "row_count": 120,
    "total_rows": 125, "failed_rows": 5, "uploader": "ada", "upload_id": "101",
    "column_names": ["id", "name", "email"], "created_at": "2026-11-01T01:02:03Z",
}]

TE_TABLES = [{"table": "organisations", "exists": True, "rowCount": 3},
             {"table": "programs", "exists": True, "rowCount": 2}]

# Import history, kept by the browser (localStorage), one job per kind of outcome.
_LOG = [{"step": "done", "level": "info", "message": "Imported 120 rows"}]
JOBS = [
    {"id": "j1", "batchId": "b1", "name": "customers.csv", "size": 2048, "status": "done", "progress": 100,
     "createdAt": 1793500000000, "insertedRows": 120, "totalRows": 125, "failedRows": 5,
     "tableName": "csv_customers", "columns": ["id", "name", "email"], "types": ["int8", "text", "text"],
     "logs": _LOG},
    {"id": "j2", "batchId": "b1", "name": "orders.csv", "size": 100, "status": "error", "progress": 100,
     "createdAt": 1793500100000, "errorMessage": "None of the 2 rows could be imported",
     "rowErrors": [{"row": 1, "column": "date", "value": "27 Oct 26", "reason": "not a timestamp"}]},
    {"id": "j3", "batchId": "b1", "name": "dup.csv", "size": 100, "status": "duplicate", "progress": 100,
     "createdAt": 1793500200000, "existingFileName": "customers.csv", "duplicateReason": "content",
     "tableName": "csv_customers"},
]

# Every upload attempt, failed ones included (the "Upload attempts" card on the upload page).
UPLOADS = [
    {"id": "101", "file_name": "orders.csv", "mode": "dynamic", "status": "failed", "total_rows": 2,
     "imported_rows": 0, "failed_rows": 2, "uploader": "ada", "uploaded_at": "2026-11-02T03:04:05Z"},
    {"id": "102", "file_name": "customers.csv", "mode": "dynamic", "status": "partly_imported",
     "total_rows": 125, "imported_rows": 120, "failed_rows": 5, "uploader": "ada",
     "uploaded_at": "2026-11-01T01:02:03Z"},
    {"id": "103", "file_name": "empty.csv", "mode": "dynamic", "status": "rejected", "total_rows": None,
     "imported_rows": None, "failed_rows": None, "uploader": "ada", "uploaded_at": "2026-11-01T00:00:00Z"},
]

REVIEW_PAGE = {
    "fileName": "customers.csv", "columns": ["id", "name"], "types": ["int8", "text"], "total": 2,
    "offset": 0, "limit": 50, "excludedRows": 0, "editedRows": 0,
    "rows": [
        {"rowNumber": 1, "original": ["1", "Ada"], "current": ["1", "Ada"], "editedColumns": [],
         "decision": "include", "decisionReason": None, "errors": []},
        {"rowNumber": 2, "original": ["x", "Bob"], "current": ["x", "Bob"], "editedColumns": [],
         "decision": "include", "decisionReason": None,
         "errors": [{"column": "id", "value": "x", "reason": '"x" is not a whole number'}]},
    ],
}

PREVIEW = {"status": "ok", "headers": ["id", "name"], "columns": ["id", "name"],
           "inferredTypes": ["int8", "text"], "sampleRows": [["1", "a"], ["2", "b"]],
           "totalRowsApprox": 2, "teTableMatch": None}

# route -> JSON body. A callable receives the request path and returns the body.
Responses = dict[str, Any]


def default_responses() -> Responses:
    return {
        "/api/csv/files": FILES,
        "/api/csv/uploads": [],
        "/api/te/tables": TE_TABLES,
        "/api/csv/preview": PREVIEW,
        "/api/auth/login": {"detail": "Invalid credentials"},
    }


def respond(path: str, responses: Responses) -> tuple[int, Any]:
    """(status, body) for one request path."""
    if path in responses:
        body = responses[path]
        body = body(path) if callable(body) else body
        # A login that is meant to fail is the only 401 in the app that stays on the page.
        return (401, body) if path == "/api/auth/login" and not _is_session(body) else (200, body)
    if path.startswith("/api/csv/uploads/") and path.endswith("/rows"):
        return 200, REVIEW_PAGE
    return 404, {"detail": f"a11y stub has no response for {path}"}


def _is_session(body: Any) -> bool:
    return isinstance(body, dict) and "token" in body


def handler(responses: Responses, unstubbed: list[str]) -> Callable:
    """A Playwright route handler. Paths with no stub are recorded in ``unstubbed``."""
    def handle(route, request):
        path = request.url.split("?")[0]
        path = path[path.index("/api/"):] if "/api/" in path else path
        status, body = respond(path, responses)
        if status == 404:
            unstubbed.append(f"{request.method} {path}")
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
    return handle


def seed_script(session: dict | None, jobs: list[dict] | None) -> str:
    """JavaScript run before the page's own scripts on every document.

    Plants the signed-in session and, when given, the import history.

    The history needs a guard. In development, React StrictMode runs the effects of
    csv-table-hub-main/src/hooks/use-local-storage.ts twice: the first pass writes the
    hook's empty default over the stored history, the second pass reads that back, so
    stored history is never shown. (A frontend bug, outside this issue; production builds
    do not double-run effects.) Without the guard the audit page would be scanned empty and
    pass without checking a single row, so writes of "[]" to that key are dropped.
    """
    parts = []
    if session is not None:
        parts.append(f"sessionStorage.setItem('te.session', {json.dumps(json.dumps(session))});")
    if jobs is not None and session is not None:
        # The app keeps history per signed-in tenant and user (#176), so plant it under that user's key.
        key = "csv-migrator:jobs:v1:{}:{}".format(quote(session["tenant"], safe=""), quote(session["username"], safe=""))
        parts.append(
            f"(() => {{ const KEY = {json.dumps(key)}, set = Storage.prototype.setItem;"
            " Storage.prototype.setItem = function (k, v) { if (k === KEY && v === '[]') return;"
            " return set.call(this, k, v); };"
            f" set.call(localStorage, KEY, {json.dumps(json.dumps(jobs))}); }})();"
        )
    return "\n".join(parts)
