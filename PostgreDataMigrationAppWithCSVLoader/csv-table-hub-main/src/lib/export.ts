// ─── src/lib/export.ts ───────────────────────────────────────────────────────
// Unified export utilities for error reports and audit data.
// Formats: CSV (always), XLSX (via SheetJS), PDF (browser print stylesheet).
//
// SheetJS is available in Lovable's environment:
//   import * as XLSX from "xlsx";
//
// PDF is implemented as a print-to-PDF helper — it opens a print-optimised
// window rather than depending on a PDF library, which keeps the bundle small
// and works offline.

import * as XLSX from "xlsx";
import type { RowError } from "./csv.functions";
import type { ColumnMapping } from "./mapping-templates";

// ─── shared types ─────────────────────────────────────────────────────────────

export type ErrorReportRow = {
  file: string;
  row_number: number | string;
  column: string;
  value: string;
  reason: string;
  plain_english: string;
  header_mapping?: string; // JSON summary of the mapping used
};

export type AuditReportRow = {
  file: string;
  status: string;
  imported_at: string;
  total_rows: number | string;
  inserted_rows: number | string;
  duplicate_rows_skipped: number | string;
  failed_rows: number | string;
  table_name: string;
  header_mapping?: string;
  cancellation_reason?: string;
};

// ─── CSV ──────────────────────────────────────────────────────────────────────

function escapeCsv(v: unknown): string {
  const s = v === undefined || v === null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsvBlob(headers: string[], rows: Record<string, unknown>[]): Blob {
  const lines = [
    headers.join(","),
    ...rows.map((r) => headers.map((h) => escapeCsv(r[h])).join(",")),
  ];
  return new Blob([lines.join("\n")], { type: "text/csv" });
}

// ─── XLSX ─────────────────────────────────────────────────────────────────────

function toXlsxBlob(
  sheetName: string,
  headers: string[],
  rows: Record<string, unknown>[],
): Blob {
  const ws = XLSX.utils.json_to_sheet(rows, { header: headers });
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName.slice(0, 31));
  const buf = XLSX.write(wb, { type: "array", bookType: "xlsx" });
  return new Blob([buf], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

// ─── PDF (print) ──────────────────────────────────────────────────────────────

function printHtml(title: string, html: string): void {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(`<!DOCTYPE html><html><head>
    <title>${title}</title>
    <style>
      body { font-family: system-ui, sans-serif; font-size: 11px; padding: 1rem; }
      h1 { font-size: 14px; margin: 0 0 .75rem; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; }
      th { background: #f1f1f1; font-weight: 600; }
      tr:nth-child(even) td { background: #fafafa; }
    </style>
  </head><body><h1>${title}</h1>${html}</body></html>`);
  w.document.close();
  w.focus();
  setTimeout(() => {
    w.print();
    w.close();
  }, 400);
}

function rowsToHtmlTable(headers: string[], rows: Record<string, unknown>[]): string {
  const ths = headers.map((h) => `<th>${h}</th>`).join("");
  const trs = rows
    .map(
      (r) =>
        `<tr>${headers.map((h) => `<td>${r[h] ?? ""}</td>`).join("")}</tr>`,
    )
    .join("");
  return `<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
}

// ─── mapping summary helper ───────────────────────────────────────────────────

export function mappingSummary(mapping?: ColumnMapping[]): string {
  if (!mapping || mapping.length === 0) return "";
  const renames = mapping
    .filter((c) => c.renamed && c.renamed !== c.original)
    .map((c) => `${c.original}→${c.renamed}`);
  return renames.length > 0 ? renames.join(", ") : "(no renames)";
}

// ─── download trigger ─────────────────────────────────────────────────────────

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ─── public API ───────────────────────────────────────────────────────────────

const ERROR_HEADERS = [
  "file",
  "row_number",
  "column",
  "value",
  "reason",
  "plain_english",
  "header_mapping",
];

const AUDIT_HEADERS = [
  "file",
  "status",
  "imported_at",
  "total_rows",
  "inserted_rows",
  "duplicate_rows_skipped",
  "failed_rows",
  "table_name",
  "header_mapping",
  "cancellation_reason",
];

export type ExportFormat = "csv" | "xlsx" | "pdf";

/** Download invalid-row / error report for a single file. */
export function downloadErrorReport(
  fileName: string,
  rows: ErrorReportRow[],
  format: ExportFormat,
): void {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const safe = fileName.replace(/\.csv$/i, "").replace(/[^a-z0-9_-]+/gi, "_");
  const base = `errors-${safe}-${ts}`;

  if (format === "csv") {
    triggerDownload(toCsvBlob(ERROR_HEADERS, rows), `${base}.csv`);
  } else if (format === "xlsx") {
    triggerDownload(toXlsxBlob("Errors", ERROR_HEADERS, rows), `${base}.xlsx`);
  } else {
    printHtml(
      `Error report — ${fileName}`,
      rowsToHtmlTable(ERROR_HEADERS, rows),
    );
  }
}

/** Download the full audit log for all jobs in the current session. */
export function downloadAuditReport(
  rows: AuditReportRow[],
  format: ExportFormat,
): void {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const base = `audit-report-${ts}`;

  if (format === "csv") {
    triggerDownload(toCsvBlob(AUDIT_HEADERS, rows), `${base}.csv`);
  } else if (format === "xlsx") {
    triggerDownload(
      toXlsxBlob("Audit", AUDIT_HEADERS, rows),
      `${base}.xlsx`,
    );
  } else {
    printHtml("Audit report", rowsToHtmlTable(AUDIT_HEADERS, rows));
  }
}

/** Build an ErrorReportRow[] from a job's rowErrors + optional mapping. */
export function buildErrorRows(
  fileName: string,
  rowErrors: RowError[],
  errorMessage?: string,
  mapping?: ColumnMapping[],
): ErrorReportRow[] {
  const mapSummary = mappingSummary(mapping);
  const rows: ErrorReportRow[] = [];

  if (errorMessage && rowErrors.length === 0) {
    rows.push({
      file: fileName,
      row_number: 0,
      column: "",
      value: "",
      reason: errorMessage,
      plain_english: errorMessage,
      header_mapping: mapSummary,
    });
  }

  for (const re of rowErrors) {
    rows.push({
      file: fileName,
      row_number: re.rowNumber,
      column: re.column ?? "",
      value: re.value ?? "",
      reason: re.reason,
      plain_english: re.reason,
      header_mapping: mapSummary,
    });
  }
  return rows;
}
