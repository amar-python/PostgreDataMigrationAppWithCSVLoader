// src/__tests__/export.test.ts
// Covers: buildErrorRows, mappingSummary, downloadErrorReport, downloadAuditReport
//
// CSV/XLSX blob output is verified by reading the generated content.
// PDF (print window) is stubbed — it cannot be rendered in jsdom.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  buildErrorRows,
  mappingSummary,
  downloadErrorReport,
  downloadAuditReport,
  type AuditReportRow,
} from "@/lib/export";
import type { RowError } from "@/lib/csv.functions";
import type { ColumnMapping } from "@/lib/mapping-templates";
import * as XLSX from "xlsx";

// ─── helpers ──────────────────────────────────────────────────────────────────

function captureBlob(): { blob: Blob | null; filename: string | null; reset: () => void } {
  const state = { blob: null as Blob | null, filename: null as string | null };
  const origCreate = URL.createObjectURL;
  const origRevoke = URL.revokeObjectURL;
  const origAppend = document.body.appendChild.bind(document.body);
  const origRemove = Element.prototype.remove;

  URL.createObjectURL = (b: Blob) => { state.blob = b; return "blob:mock"; };
  URL.revokeObjectURL = vi.fn();

  // Intercept <a> click to capture filename
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    state.filename = this.download;
  });

  return {
    ...state,
    get blob() { return state.blob; },
    get filename() { return state.filename; },
    reset() {
      URL.createObjectURL = origCreate;
      URL.revokeObjectURL = origRevoke;
      vi.restoreAllMocks();
    },
  };
}

// ─── mappingSummary ───────────────────────────────────────────────────────────

describe("mappingSummary", () => {
  it("returns empty string for undefined input", () => {
    expect(mappingSummary(undefined)).toBe("");
  });

  it("returns empty string for an empty mapping", () => {
    expect(mappingSummary([])).toBe("");
  });

  it("returns '(no renames)' when every column keeps its original name", () => {
    const m: ColumnMapping[] = [
      { original: "a", renamed: "a", type: "text" },
      { original: "b", renamed: "b", type: "text" },
    ];
    expect(mappingSummary(m)).toBe("(no renames)");
  });

  it("returns '(no renames)' when renamed is empty string", () => {
    const m: ColumnMapping[] = [{ original: "a", renamed: "", type: "text" }];
    expect(mappingSummary(m)).toBe("(no renames)");
  });

  it("lists renamed columns as 'original→renamed'", () => {
    const m: ColumnMapping[] = [
      { original: "First Name", renamed: "first_name", type: "text" },
      { original: "Last Name", renamed: "last_name", type: "text" },
    ];
    expect(mappingSummary(m)).toBe("First Name→first_name, Last Name→last_name");
  });

  it("omits columns that are unchanged", () => {
    const m: ColumnMapping[] = [
      { original: "id", renamed: "id", type: "int8" },
      { original: "email", renamed: "contact_email", type: "text" },
    ];
    expect(mappingSummary(m)).toBe("email→contact_email");
  });
});

// ─── buildErrorRows ───────────────────────────────────────────────────────────

describe("buildErrorRows", () => {
  const rowErrors: RowError[] = [
    { rowNumber: 3, column: "amount", value: "not-a-number", reason: "expected numeric" },
    { rowNumber: 7, column: "date", value: "99/99/99", reason: "invalid date" },
  ];
  const mapping: ColumnMapping[] = [
    { original: "Amount", renamed: "amount", type: "numeric" },
  ];

  it("returns one row per RowError", () => {
    const rows = buildErrorRows("test.csv", rowErrors);
    expect(rows).toHaveLength(2);
  });

  it("maps rowNumber, column, value, reason correctly", () => {
    const [first] = buildErrorRows("test.csv", rowErrors);
    expect(first.row_number).toBe(3);
    expect(first.column).toBe("amount");
    expect(first.value).toBe("not-a-number");
    expect(first.reason).toBe("expected numeric");
  });

  it("includes the file name in every row", () => {
    const rows = buildErrorRows("my-data.csv", rowErrors);
    rows.forEach((r) => expect(r.file).toBe("my-data.csv"));
  });

  it("includes a mapping summary when mapping is provided", () => {
    const rows = buildErrorRows("f.csv", rowErrors, undefined, mapping);
    rows.forEach((r) => expect(r.header_mapping).toContain("Amount→amount"));
  });

  it("when rowErrors is empty but errorMessage is set, emits one structural-error row", () => {
    const rows = buildErrorRows("f.csv", [], "File is empty", undefined);
    expect(rows).toHaveLength(1);
    expect(rows[0].row_number).toBe(0);
    expect(rows[0].reason).toBe("File is empty");
  });

  it("returns empty array when both rowErrors and errorMessage are absent", () => {
    expect(buildErrorRows("f.csv", [])).toHaveLength(0);
  });
});

// ─── downloadErrorReport — CSV ─────────────────────────────────────────────────

describe("downloadErrorReport CSV", () => {
  let cap: ReturnType<typeof captureBlob>;

  beforeEach(() => { cap = captureBlob(); });
  afterEach(() => { cap.reset(); });

  it("triggers a download with a .csv filename", () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 1, column: "x", value: "bad", reason: "wrong type" },
    ]);
    downloadErrorReport("data.csv", rows, "csv");
    expect(cap.filename).toMatch(/errors-data.*\.csv$/);  // extension stripped before sanitise
  });

  it("CSV content contains the header row", async () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 2, column: "y", value: "oops", reason: "null not allowed" },
    ]);
    downloadErrorReport("data.csv", rows, "csv");
    const text = await cap.blob!.text();
    expect(text).toContain("file,row_number,column,value,reason,plain_english");
  });

  it("CSV content contains the error row values", async () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 5, column: "amount", value: "abc", reason: "expected int" },
    ]);
    downloadErrorReport("data.csv", rows, "csv");
    const text = await cap.blob!.text();
    expect(text).toContain("5");
    expect(text).toContain("amount");
    expect(text).toContain("abc");
  });

  it("escapes commas and quotes in values", async () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 1, column: "desc", value: 'say "hello", world', reason: "test" },
    ]);
    downloadErrorReport("data.csv", rows, "csv");
    const text = await cap.blob!.text();
    // value should be quoted
    expect(text).toContain('"say ""hello"", world"');
  });
});

// ─── downloadErrorReport — XLSX ────────────────────────────────────────────────

describe("downloadErrorReport XLSX", () => {
  let cap: ReturnType<typeof captureBlob>;

  beforeEach(() => { cap = captureBlob(); });
  afterEach(() => { cap.reset(); });

  it("triggers a download with a .xlsx filename", () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 1, column: "x", value: "bad", reason: "wrong" },
    ]);
    downloadErrorReport("data.csv", rows, "xlsx");
    expect(cap.filename).toMatch(/errors-data.*\.xlsx$/);
  });

  it("XLSX content is a valid workbook with an Errors sheet", async () => {
    const rows = buildErrorRows("data.csv", [
      { rowNumber: 3, column: "col", value: "v", reason: "r" },
    ]);
    downloadErrorReport("data.csv", rows, "xlsx");
    const buf = await cap.blob!.arrayBuffer();
    const wb = XLSX.read(buf, { type: "array" });
    expect(wb.SheetNames).toContain("Errors");
    const ws = wb.Sheets["Errors"];
    const parsed = XLSX.utils.sheet_to_json(ws);
    expect(parsed).toHaveLength(1);
    expect((parsed[0] as any).row_number).toBe(3);
  });
});

// ─── downloadAuditReport ──────────────────────────────────────────────────────

describe("downloadAuditReport", () => {
  let cap: ReturnType<typeof captureBlob>;

  beforeEach(() => { cap = captureBlob(); });
  afterEach(() => { cap.reset(); });

  const rows: AuditReportRow[] = [
    { file: "a.csv", status: "Imported", imported_at: "2026-01-01T00:00:00Z", total_rows: 10, inserted_rows: 9, duplicate_rows_skipped: 1, failed_rows: 0, table_name: "csv_abc", header_mapping: "", cancellation_reason: "" },
  ];

  it("CSV: triggers download with audit-report filename", () => {
    downloadAuditReport(rows, "csv");
    expect(cap.filename).toMatch(/audit-report.*\.csv$/);
  });

  it("XLSX: workbook has an Audit sheet", async () => {
    downloadAuditReport(rows, "xlsx");
    const buf = await cap.blob!.arrayBuffer();
    const wb = XLSX.read(buf, { type: "array" });
    expect(wb.SheetNames).toContain("Audit");
    const parsed = XLSX.utils.sheet_to_json(wb.Sheets["Audit"]);
    expect((parsed[0] as any).status).toBe("Imported");
  });

  it("CSV: includes header and data row", async () => {
    downloadAuditReport(rows, "csv");
    const text = await cap.blob!.text();
    expect(text).toContain("file,status,imported_at");
    expect(text).toContain("a.csv");
    expect(text).toContain("Imported");
  });
});
