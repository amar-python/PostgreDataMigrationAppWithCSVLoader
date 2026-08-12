// ─── src/lib/job-outcome.ts ───────────────────────────────────────────────────
// Pure decision logic extracted from the runJob/cancelJob/requestOverwrite
// state machine in routes/_authenticated/index.tsx so it's unit-testable
// without rendering the full Uploader component (which needs TanStack Router
// context — see the same rationale in __tests__/audit-filters.test.ts).
//
// index.tsx still owns all side effects (setJobs, toast, Notification,
// router.invalidate, AbortController) — these functions only decide *what*
// should happen, given an upload result / thrown error / job state.

import type { Job } from "./job-types";
import type { UploadResult } from "./csv.functions";
import type { ColumnMapping } from "./mapping-templates";

export type JobOutcome = {
  patch: Partial<Job>;
  toast: { type: "success" | "warning" | "error"; message: string };
  notify?: { title: string; body: string };
  invalidateRoute?: boolean;
};

export function classifyUploadResult(
  jobName: string,
  res: UploadResult,
  mapping?: ColumnMapping[],
): JobOutcome {
  if (res.status === "ok") {
    const msg = `${jobName}: ${res.overwritten ? "overwrote · " : ""}${res.insertedRows} of ${res.totalRows} rows imported${res.failedRows ? ` · ${res.failedRows} failed` : ""}`;
    return {
      patch: {
        status: "done",
        progress: 100,
        insertedRows: res.insertedRows,
        duplicateRowsSkipped: res.duplicateRowsSkipped,
        failedRows: res.failedRows,
        totalRows: res.totalRows,
        tableName: res.tableName,
        columns: res.columns,
        types: res.types,
        rowErrors: res.rowErrors,
        logs: res.logs,
        overwritten: res.overwritten,
        replacedFileName: res.replacedFileName,
        headerMapping: mapping,
      },
      toast: { type: "success", message: msg },
      notify: { title: "Import complete", body: msg },
      invalidateRoute: true,
    };
  }

  if (res.status === "duplicate_file") {
    const msg = `${jobName}: already imported — click Overwrite to replace.`;
    return {
      patch: {
        status: "duplicate",
        progress: 100,
        existingFileName: res.existingFileName,
        tableName: res.tableName,
        duplicateReason: res.reason,
        existingRowCount: res.existingRowCount,
        logs: res.logs,
        headerMapping: mapping,
      },
      toast: { type: "warning", message: msg },
      notify: { title: "Duplicate detected", body: `${jobName} matches an existing import.` },
    };
  }

  if (res.status === "invalid_structure") {
    return {
      patch: {
        status: "error",
        progress: 100,
        errorMessage: res.message,
        errorDetails: res.message,
        invalidReason: res.reason,
        logs: res.logs,
        headerMapping: mapping,
      },
      toast: { type: "error", message: `${jobName}: ${res.message}` },
      notify: { title: "Import failed", body: `${jobName}: ${res.message}` },
    };
  }

  // res.status === "error" — the discriminated union narrows on its own from
  // the checks above, no cast needed.
  return {
    patch: {
      status: "error",
      progress: 100,
      errorMessage: res.message,
      errorDetails: res.message,
      rowErrors: res.rowErrors,
      logs: res.logs,
      headerMapping: mapping,
    },
    toast: { type: "error", message: `${jobName}: ${res.message}` },
    notify: { title: "Import failed", body: `${jobName}: ${res.message}` },
  };
}

export function classifyThrownError(jobName: string, err: unknown): JobOutcome {
  const e = err as Error | undefined;
  const message = e?.message || "Unknown error";
  return {
    patch: {
      status: "error",
      progress: 100,
      errorMessage: message,
      errorDetails: e?.message,
      errorStack: e?.stack,
    },
    toast: { type: "error", message: `${jobName}: ${message}` },
    // Deliberately no `notify` here — matches the pre-extraction behaviour,
    // where the catch block never called sendNotif (only the four
    // classifyUploadResult branches do).
  };
}

export function buildCancelPatch(reason?: string): Partial<Job> {
  return { status: "cancelled", progress: 100, cancellationReason: reason ?? "Cancelled by user" };
}

export function buildCancelToastMessage(reason?: string): string {
  return `Import cancelled${reason ? `: ${reason}` : ""}.`;
}

export type OverwriteAction = { action: "show-diff"; job: Job } | { action: "retry-overwrite" };

export function decideOverwriteAction(job: Job | undefined): OverwriteAction {
  if (job?.tableName) return { action: "show-diff", job };
  return { action: "retry-overwrite" };
}
