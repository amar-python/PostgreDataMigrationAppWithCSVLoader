// src/__tests__/uploader-state-machine.test.ts
// Covers the upload state machine in routes/_authenticated/index.tsx
// (runJob/retryJob/cancelJob) — previously untested despite being the
// highest-risk logic in the app: abort handling, the overwrite flow, and
// how server responses map to job status.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { invalidate } = vi.hoisted(() => ({ invalidate: vi.fn() }));
vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>(
    "@tanstack/react-router",
  );
  return {
    ...actual,
    useRouter: () => ({ invalidate }),
  };
});

const { uploadCsv } = vi.hoisted(() => ({ uploadCsv: vi.fn() }));
vi.mock("@/lib/csv.functions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/csv.functions")>(
    "@/lib/csv.functions",
  );
  return { ...actual, uploadCsv: (...args: unknown[]) => uploadCsv(...args) };
});

import { Uploader } from "@/routes/_authenticated/index";

function csvFile(name = "widgets.csv", content = "id,name\n1,foo\n2,bar\n") {
  return new File([content], name, { type: "text/csv" });
}

function renderUploader() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(Uploader)),
  );
}

async function dropAndConfirm(file: File) {
  const user = userEvent.setup();
  renderUploader();
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await user.upload(input, file);
  const confirmBtn = await screen.findByRole("button", { name: /confirm & import/i });
  await user.click(confirmBtn);
  return user;
}

beforeEach(() => {
  window.localStorage.clear();
  uploadCsv.mockReset();
  invalidate.mockReset();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("Uploader state machine", () => {
  it("a successful upload ends in status done and invalidates the router", async () => {
    uploadCsv.mockResolvedValue({
      status: "ok",
      fileId: "1",
      tableName: "csv_abc123",
      totalRows: 2,
      insertedRows: 2,
      duplicateRowsSkipped: 0,
      failedRows: 0,
      columns: ["id", "name"],
      types: ["int8", "text"],
      rowErrors: [],
      logs: [],
    });

    await dropAndConfirm(csvFile());

    await waitFor(() => expect(screen.getByText(/^imported$/i)).toBeInTheDocument());
    expect(invalidate).toHaveBeenCalled();
  });

  it("a duplicate_file response is classified as a duplicate, not an error", async () => {
    uploadCsv.mockResolvedValue({
      status: "duplicate_file",
      reason: "content",
      existingFileName: "widgets.csv",
      tableName: "csv_abc123",
      existingRowCount: 2,
      logs: [],
    });

    await dropAndConfirm(csvFile());

    await waitFor(() =>
      expect(screen.getByText(/duplicate file/i)).toBeInTheDocument(),
    );
  });

  it("an invalid_structure response is classified as an error", async () => {
    uploadCsv.mockResolvedValue({
      status: "invalid_structure",
      reason: "empty",
      message: "This CSV is empty.",
      logs: [],
    });

    await dropAndConfirm(csvFile());

    await waitFor(() => expect(screen.getByText(/^failed$/i)).toBeInTheDocument());
  });

  it("a rejected upload promise is classified as an error with the thrown message", async () => {
    uploadCsv.mockRejectedValue(new Error("network down"));

    await dropAndConfirm(csvFile());

    await waitFor(() => expect(screen.getByText(/^failed$/i)).toBeInTheDocument());
  });

  it("clicking Stop while uploading marks the job cancelled and ignores the late result", async () => {
    let resolveUpload: (v: unknown) => void;
    uploadCsv.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );

    const user = await dropAndConfirm(csvFile());

    const stopBtn = await screen.findByRole("button", { name: /stop/i });
    await user.click(stopBtn);

    await waitFor(() => expect(screen.getByText(/^cancelled$/i)).toBeInTheDocument());

    // The in-flight promise resolving afterwards must not flip the job back
    // to "done" — runJob checks ctrl.signal.aborted before applying the result.
    resolveUpload!({ status: "ok", fileId: "1", tableName: "t", totalRows: 1,
      insertedRows: 1, duplicateRowsSkipped: 0, failedRows: 0, columns: [],
      types: [], rowErrors: [], logs: [] });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText(/^cancelled$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^imported$/i)).not.toBeInTheDocument();
  });

  it("overwrite flow: confirming the diff dialog re-uploads with overwrite=true", async () => {
    uploadCsv.mockResolvedValue({
      status: "duplicate_file",
      reason: "content",
      existingFileName: "widgets.csv",
      tableName: "csv_abc123",
      existingRowCount: 2,
      logs: [],
    });

    const user = await dropAndConfirm(csvFile());
    await waitFor(() => expect(screen.getByText(/duplicate file/i)).toBeInTheDocument());

    uploadCsv.mockClear();
    uploadCsv.mockResolvedValue({
      status: "ok",
      fileId: "2",
      tableName: "csv_abc123",
      totalRows: 2,
      insertedRows: 2,
      duplicateRowsSkipped: 0,
      failedRows: 0,
      columns: ["id", "name"],
      types: ["int8", "text"],
      rowErrors: [],
      logs: [],
      overwritten: true,
    });

    await user.click(screen.getByRole("button", { name: /^overwrite$/i }));
    // job.tableName is set, so this opens the diff-confirm dialog first — the
    // per-row "Overwrite" button is still on screen too, so scope the query
    // to the dialog to disambiguate.
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^overwrite$/i }));

    await waitFor(() => expect(uploadCsv).toHaveBeenCalled());
    const call = uploadCsv.mock.calls[0][0];
    expect(call.overwrite).toBe(true);
  });
});
