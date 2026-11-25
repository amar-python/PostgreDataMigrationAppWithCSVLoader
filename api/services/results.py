"""The shapes the CSV loaders return (#323).

Every upload path (``upload_dynamic``, ``upload_te``) answers with a :class:`LoadResult`: one ``status`` and the fields
that status carries. The route adds ``uploadId`` and removes ``_duplicateFlags`` before replying. A misspelt key, such
as ``result["_duplicateFlag"]`` or a field a loader never sets, is now a type error (``make typecheck``) instead of a
``KeyError`` or a silent ``None`` at run time.

These are types only: at run time each is a plain ``dict``, so nothing about the JSON the API returns changes.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from typing_extensions import NotRequired, Required

Status = Literal["ok", "error", "duplicate_file", "invalid_structure", "staged"]  # "staged": api/services/staged_import.stage


class LogEntry(TypedDict):
    """One step of an upload's log, as the response's ``logs`` lists it."""

    ts: NotRequired[int]  # absent on the closing entry originals.store_upload adds for a failed attempt
    step: str
    level: str
    message: str
    count: NotRequired[int]


class RowError(TypedDict):
    """A row that could not be loaded. A row the database refused names no column (``RowErrors.add_db_error``)."""

    rowNumber: int
    column: NotRequired[str]
    value: NotRequired[str]
    reason: str | None


class DuplicateFlag(TypedDict):
    """BR-29: a row whose exact content is already in an earlier version of the dataset."""

    rowNumber: int
    matchedFileId: str
    matchedFileName: str
    matchedVersion: int


class SchemaCheck(TypedDict):
    """How a new version's columns compare with the previous version's (informational)."""

    compatible: bool
    added: list[str]
    removed: list[str]
    changed: list[dict[str, str]]
    comparedTo: NotRequired[dict[str, Any]]


class LoadFields(TypedDict, total=False):
    """Every field a load result can carry except ``status``. The result builders in load_common take these as
    keyword arguments (``**fields: Unpack[LoadFields]``), so a misspelt or mistyped field fails the type check."""

    logs: list[LogEntry]  # always present at run time
    message: str
    reason: str
    # status "ok"
    fileId: str
    tableName: str
    totalRows: int
    insertedRows: int
    duplicateRowsSkipped: int
    failedRows: int
    columns: list[str]
    types: list[str]
    typesProvenance: str
    rowErrors: list[RowError]
    dataset: str
    version: int
    schemaCheck: SchemaCheck | None
    duplicateRowsAcrossUploads: int
    crossUploadDuplicates: list[DuplicateFlag]
    _duplicateFlags: list[DuplicateFlag]  # the full list, for store_upload; the route removes it before replying
    overwritten: bool
    replacedFileName: str | None
    # status "duplicate_file"
    existingFileName: str
    existingRowCount: int
    existingMode: str
    # added by the route (POST /api/csv/upload)
    uploadId: str | None


class LoadResult(LoadFields, total=False):
    """What a loader returns: a ``status``, its ``logs``, and the fields that status carries."""

    status: Required[Status]
