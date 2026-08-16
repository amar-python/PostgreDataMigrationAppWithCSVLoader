// ─── src/lib/job-types.ts ─────────────────────────────────────────────────────
// Shared Job/JobStatus types for the upload page (index.tsx) and the audit
// log (audit.tsx) — previously hand-duplicated in both files (plus a third
// copy in __tests__/audit-filters.test.ts), which let them drift apart.

import type { RowError, ColumnType, ProcessingLog } from "./csv.functions";
import type { ColumnMapping } from "./mapping-templates";

export type JobStatus =
  | "reading"
  | "uploading"
  | "processing"
  | "done"
  | "duplicate"
  | "error"
  | "interrupted"
  | "cancelled";

export type Job = {
  id: string;
  batchId: string;
  name: string;
  size: number;
  status: JobStatus;
  progress: number;
  createdAt: number;
  insertedRows?: number;
  duplicateRowsSkipped?: number;
  failedRows?: number;
  totalRows?: number;
  tableName?: string;
  existingFileName?: string;
  duplicateReason?: "content" | "name" | "empty";
  invalidReason?: "empty" | "header_only" | "no_columns";
  existingRowCount?: number;
  overwritten?: boolean;
  replacedFileName?: string | null;
  errorMessage?: string;
  errorDetails?: string;
  errorStack?: string;
  rowErrors?: RowError[];
  columns?: string[];
  types?: ColumnType[];
  logs?: ProcessingLog[];
  headerMapping?: ColumnMapping[];
  cancellationReason?: string;
  mode?: "dynamic" | "te";
  targetTable?: string;
};
