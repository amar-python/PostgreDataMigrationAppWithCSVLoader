// Client-side CSV preview and type inference. Mirrors the server parser.
import type { ColumnType } from "./csv.functions";

export type CsvPreview = {
  headers: string[];
  sanitizedHeaders: string[];
  sampleRows: string[][];
  inferredTypes: ColumnType[];
  totalRowsApprox: number;
  bytesRead: number;
  bytesTotal: number;
  truncated: boolean;
};

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  let i = 0;
  const src = text.replace(/^\uFEFF/, "");
  while (i < src.length) {
    const ch = src[i];
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i++; continue;
      }
      field += ch; i++; continue;
    }
    if (ch === '"') { inQuotes = true; i++; continue; }
    if (ch === ",") { row.push(field); field = ""; i++; continue; }
    if (ch === "\r") { i++; continue; }
    if (ch === "\n") { row.push(field); rows.push(row); row = []; field = ""; i++; continue; }
    field += ch; i++;
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  while (rows.length && rows[rows.length - 1].every((c) => c === "")) rows.pop();
  return rows;
}

export function sanitizeColumns(headers: string[]): string[] {
  const reserved = new Set(["_id", "_row_hash", "_created_at"]);
  const seen = new Map<string, number>();
  return headers.map((h, idx) => {
    let base = (h || `column_${idx + 1}`)
      .toLowerCase().trim()
      .replace(/[^a-z0-9_]+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (!base) base = `column_${idx + 1}`;
    if (/^[0-9]/.test(base)) base = `col_${base}`;
    if (reserved.has(base)) base = `${base}_col`;
    if (base.length > 55) base = base.slice(0, 55);
    let name = base;
    const count = seen.get(base) ?? 0;
    if (count > 0) name = `${base}_${count + 1}`;
    seen.set(base, count + 1);
    return name;
  });
}

const INT_RE = /^-?\d+$/;
const NUM_RE = /^-?\d+(\.\d+)?$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const BOOL_TRUE = new Set(["true", "t", "yes", "y", "1"]);
const BOOL_FALSE = new Set(["false", "f", "no", "n", "0"]);

function inferCell(v: string): Set<ColumnType> {
  const s = v.trim();
  if (s === "") return new Set(["int8", "numeric", "date", "timestamptz", "boolean", "text"]);
  const out = new Set<ColumnType>(["text"]);
  if (INT_RE.test(s)) out.add("int8");
  if (NUM_RE.test(s)) out.add("numeric");
  if (DATE_RE.test(s)) out.add("date");
  const lower = s.toLowerCase();
  if (BOOL_TRUE.has(lower) || BOOL_FALSE.has(lower)) out.add("boolean");
  // timestamptz: anything Date parses that also has a T or space + colon
  if (!DATE_RE.test(s) && /[T ]\d/.test(s) && !isNaN(new Date(s).getTime())) {
    out.add("timestamptz");
  } else if (DATE_RE.test(s)) {
    // date is already added; also timestamptz-compatible
    out.add("timestamptz");
  }
  return out;
}

function pickType(candidates: Set<ColumnType>): ColumnType {
  // Narrowest first
  const order: ColumnType[] = ["boolean", "int8", "numeric", "date", "timestamptz", "text"];
  for (const t of order) if (candidates.has(t)) return t;
  return "text";
}

export async function parseCsvPreview(file: File, opts?: { sampleRows?: number; maxBytes?: number }): Promise<CsvPreview> {
  const maxBytes = opts?.maxBytes ?? 512 * 1024; // 512KB for preview
  const sampleCount = opts?.sampleRows ?? 10;
  const inferRowLimit = 200;

  const slice = file.slice(0, Math.min(file.size, maxBytes));
  const text = await slice.text();
  const truncated = file.size > slice.size;
  // If truncated, drop the last (possibly partial) row.
  const rows = parseCsv(text);
  if (truncated && rows.length > 1) rows.pop();

  if (rows.length === 0) {
    return {
      headers: [], sanitizedHeaders: [], sampleRows: [], inferredTypes: [],
      totalRowsApprox: 0, bytesRead: slice.size, bytesTotal: file.size, truncated,
    };
  }

  const headers = rows[0];
  const sanitized = sanitizeColumns(headers);
  const dataRows = rows.slice(1);
  const sample = dataRows.slice(0, sampleCount);

  // Infer types
  const perCol: Set<ColumnType>[] = headers.map(() => new Set(["int8", "numeric", "date", "timestamptz", "boolean", "text"]));
  for (let r = 0; r < Math.min(dataRows.length, inferRowLimit); r++) {
    const row = dataRows[r];
    for (let c = 0; c < headers.length; c++) {
      const cell = row[c] ?? "";
      const cands = inferCell(cell);
      // intersect
      for (const t of Array.from(perCol[c])) {
        if (!cands.has(t)) perCol[c].delete(t);
      }
      if (perCol[c].size === 1 && perCol[c].has("text")) continue;
    }
  }
  const inferredTypes = perCol.map(pickType);

  // Approximate total rows: extrapolate from bytesRead
  let totalRowsApprox = dataRows.length;
  if (truncated && slice.size > 0) {
    totalRowsApprox = Math.round((dataRows.length / slice.size) * file.size);
  }

  return {
    headers, sanitizedHeaders: sanitized, sampleRows: sample, inferredTypes,
    totalRowsApprox, bytesRead: slice.size, bytesTotal: file.size, truncated,
  };
}

export const COLUMN_TYPE_LABEL: Record<ColumnType, string> = {
  int8: "Whole number",
  numeric: "Number",
  date: "Date",
  timestamptz: "Timestamp",
  boolean: "True/False",
  text: "Text",
};
