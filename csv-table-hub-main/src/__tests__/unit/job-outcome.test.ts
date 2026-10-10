// src/__tests__/job-outcome.test.ts
// Unit tests for the pure decision logic extracted from the runJob/cancelJob/
// requestOverwrite state machine (src/lib/job-outcome.ts). Complements
// uploader-state-machine.test.ts, which drives the same logic end-to-end
// through the rendered Uploader component; these tests pin down the exact
// patch/toast/notify shape each branch produces in isolation.

import { describe, it, expect } from "vitest";
import {
  classifyUploadResult, classifyThrownError, buildCancelPatch,
  buildCancelToastMessage, decideOverwriteAction,
} from "@/lib/job-outcome";
import type { UploadResult } from "@/lib/csv.functions";
import type { Job } from "@/lib/job-types";

describe("classifyUploadResult", () => {
  it("status ok -> done, success toast, notify, and invalidateRoute", () => {
    const res: UploadResult = {
      status: "ok", fileId: "1", tableName: "csv_abc", totalRows: 10,
      insertedRows: 9, duplicateRowsSkipped: 1, failedRows: 0,
      columns: ["a"], types: ["text"], rowErrors: [], logs: [],
    };
    const outcome = classifyUploadResult("widgets.csv", res);
    expect(outcome.patch.status).toBe("done");
    expect(outcome.patch.progress).toBe(100);
    expect(outcome.patch.insertedRows).toBe(9);
    expect(outcome.toast).toEqual({ type: "success", message: "widgets.csv: 9 of 10 rows imported" });
    expect(outcome.notify?.title).toBe("Import complete");
    expect(outcome.invalidateRoute).toBe(true);
  });

  it("status ok with overwritten and failedRows composes the full message", () => {
    const res: UploadResult = {
      status: "ok", fileId: "1", tableName: "csv_abc", totalRows: 10,
      insertedRows: 8, duplicateRowsSkipped: 0, failedRows: 2,
      columns: [], types: [], rowErrors: [], logs: [], overwritten: true,
    };
    const outcome = classifyUploadResult("widgets.csv", res);
    expect(outcome.toast.message).toBe(
      "widgets.csv: overwrote · 8 of 10 rows imported · 2 failed",
    );
    expect(outcome.patch.overwritten).toBe(true);
  });

  it("status duplicate_file -> duplicate patch, warning toast, no invalidateRoute", () => {
    const res: UploadResult = {
      status: "duplicate_file", reason: "content", existingFileName: "widgets.csv",
      tableName: "csv_abc", existingRowCount: 5, logs: [],
    };
    const outcome = classifyUploadResult("widgets.csv", res);
    expect(outcome.patch.status).toBe("duplicate");
    expect(outcome.patch.duplicateReason).toBe("content");
    expect(outcome.toast.type).toBe("warning");
    expect(outcome.invalidateRoute).toBeUndefined();
  });

  it("status invalid_structure -> error patch carrying invalidReason", () => {
    const res: UploadResult = {
      status: "invalid_structure", reason: "empty", message: "This CSV is empty.", logs: [],
    };
    const outcome = classifyUploadResult("widgets.csv", res);
    expect(outcome.patch.status).toBe("error");
    expect(outcome.patch.invalidReason).toBe("empty");
    expect(outcome.patch.errorMessage).toBe("This CSV is empty.");
    expect(outcome.toast).toEqual({ type: "error", message: "widgets.csv: This CSV is empty." });
  });

  it("status error -> error patch carrying rowErrors", () => {
    const res: UploadResult = {
      status: "error", message: "DB is on fire",
      rowErrors: [{ rowNumber: 3, reason: "bad cast" }], logs: [],
    };
    const outcome = classifyUploadResult("widgets.csv", res);
    expect(outcome.patch.status).toBe("error");
    expect(outcome.patch.rowErrors).toEqual([{ rowNumber: 3, reason: "bad cast" }]);
    expect(outcome.toast.message).toBe("widgets.csv: DB is on fire");
  });

  it("passes the header mapping through to the patch on every branch", () => {
    const mapping = [{ original: "a", renamed: "b", type: "text" as const }];
    const res: UploadResult = { status: "error", message: "x", logs: [] };
    expect(classifyUploadResult("f.csv", res, mapping).patch.headerMapping).toBe(mapping);
  });
});

describe("classifyThrownError", () => {
  it("uses the error's message and stack, and never sets `notify`", () => {
    const err = new Error("network down");
    const outcome = classifyThrownError("widgets.csv", err);
    expect(outcome.patch.status).toBe("error");
    expect(outcome.patch.errorMessage).toBe("network down");
    expect(outcome.patch.errorStack).toBe(err.stack);
    expect(outcome.toast).toEqual({ type: "error", message: "widgets.csv: network down" });
    expect(outcome.notify).toBeUndefined();
  });

  it("falls back to 'Unknown error' when the thrown value has no message", () => {
    const outcome = classifyThrownError("widgets.csv", {});
    expect(outcome.patch.errorMessage).toBe("Unknown error");
    expect(outcome.toast.message).toBe("widgets.csv: Unknown error");
  });
});

describe("buildCancelPatch / buildCancelToastMessage", () => {
  it("defaults the cancellation reason when none is given", () => {
    expect(buildCancelPatch()).toEqual({
      status: "cancelled", progress: 100, cancellationReason: "Cancelled by user",
    });
    expect(buildCancelToastMessage()).toBe("Import cancelled.");
  });

  it("carries an explicit reason through to both the patch and the toast", () => {
    expect(buildCancelPatch("timed out").cancellationReason).toBe("timed out");
    expect(buildCancelToastMessage("timed out")).toBe("Import cancelled: timed out.");
  });
});

describe("decideOverwriteAction", () => {
  const baseJob: Job = {
    id: "1", batchId: "b1", name: "f.csv", size: 10, status: "duplicate",
    progress: 100, createdAt: 0,
  };

  it("shows the diff dialog when the job already has a tableName", () => {
    const job = { ...baseJob, tableName: "csv_abc" };
    expect(decideOverwriteAction(job)).toEqual({ action: "show-diff", job });
  });

  it("retries directly with overwrite when there is no tableName yet", () => {
    expect(decideOverwriteAction(baseJob)).toEqual({ action: "retry-overwrite" });
  });

  it("retries directly when the job is undefined (id no longer in the list)", () => {
    expect(decideOverwriteAction(undefined)).toEqual({ action: "retry-overwrite" });
  });
});
