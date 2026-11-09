// #187 (BR-25): a failed upload has no migrated file, so it must be reachable from the
// upload-attempt registry, and the upload response must keep its uploadId.

import { afterEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { uploadCsv, type UploadAttempt } from "@/lib/csv.functions";
import { needsAttention } from "@/lib/job-outcome";

vi.mock("@tanstack/react-router", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({
      to,
      params,
      children,
    }: {
      to: string;
      params: Record<string, string>;
      children: unknown;
    }) => <a href={to.replace("$uploadId", params.uploadId)}>{children as never}</a>,
  };
});

import { UploadAttempts } from "@/routes/_authenticated/index";

const attempt = (id: string, status: string, failed = 0): UploadAttempt => ({
  id,
  file_name: `${status}_${id}.csv`,
  mode: "dynamic",
  status,
  total_rows: 3,
  imported_rows: 3 - failed,
  failed_rows: failed,
  uploaded_at: "2026-11-09T00:00:00Z",
});

afterEach(() => vi.unstubAllGlobals());

const logs = [{ ts: 1, step: "done", level: "info", message: "m" }];
const ok = {
  status: "ok",
  fileId: "1",
  tableName: "csv_a",
  totalRows: 3,
  insertedRows: 3,
  duplicateRowsSkipped: 0,
  failedRows: 0,
  columns: ["a"],
  types: ["text"],
  rowErrors: [],
  logs,
};

it("keeps uploadId on success, partial and all-failed responses", async () => {
  const bodies = [
    { ...ok, uploadId: "11" },
    { ...ok, insertedRows: 1, failedRows: 2, uploadId: "12" },
    { status: "error", message: "every row failed", rowErrors: [], logs, uploadId: "13" },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(bodies.shift()))),
  );
  const ids = [];
  for (let i = 0; i < 3; i++) {
    const res = await uploadCsv({ fileName: "a.csv", content: "a\n1\n" });
    ids.push((res as { uploadId?: string | null }).uploadId);
  }
  expect(ids).toEqual(["11", "12", "13"]);
});

it("lists an all-failed upload with a review link, hiding clean imports by default", async () => {
  const user = userEvent.setup();
  render(
    <UploadAttempts
      uploads={[
        attempt("1", "imported"),
        attempt("2", "failed", 3),
        attempt("3", "partly_imported", 1),
      ]}
    />,
  );
  expect(screen.getByText("failed_2.csv")).toBeInTheDocument();
  expect(screen.getByText("partly_imported_3.csv")).toBeInTheDocument();
  expect(screen.queryByText("imported_1.csv")).not.toBeInTheDocument();
  expect(
    screen.getAllByRole("link", { name: "Review" }).map((a) => a.getAttribute("href")),
  ).toEqual(["/review/2", "/review/3"]);
  expect(screen.getByText("3 of 3 rows failed")).toBeInTheDocument();

  await user.click(screen.getByLabelText(/only failed or partial/i));
  expect(screen.getByText("imported_1.csv")).toBeInTheDocument();
});

it("gives a rejected upload no review link, since nothing was stored to review", () => {
  render(<UploadAttempts uploads={[attempt("4", "rejected")]} />);
  expect(screen.getByText("rejected_4.csv")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Review" })).not.toBeInTheDocument();
});

it("renders nothing without any upload attempts", () => {
  const { container } = render(<UploadAttempts uploads={[]} />);
  expect(container).toBeEmptyDOMElement();
});

it("needsAttention flags failed, partial and rejected only", () => {
  expect(["failed", "partly_imported", "rejected"].every(needsAttention)).toBe(true);
  expect(["imported", "duplicate"].some(needsAttention)).toBe(false);
});
