// #195: dynamic-mode column types are confirmed before a table exists, and the
// provenance of the types is shown. The frontend half of the contract:
//   - uploadCsv sends `typesConfirmed` (default false) alongside `types`
//   - the response schema accepts "types_unconfirmed" and `typesProvenance`
//   - the files list schema accepts `types_provenance` (null for T&E files)
//   - a "types_unconfirmed" reply surfaces as a visible error, never a silent success
import { afterEach, describe, expect, it, vi } from "vitest";
import { listCsvFiles, uploadCsv } from "@/lib/csv.functions";
import { classifyUploadResult } from "@/lib/job-outcome";

function mockFetchJson(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const sentBody = (m: ReturnType<typeof vi.fn>) => JSON.parse(m.mock.calls[0][1].body as string);

afterEach(() => vi.unstubAllGlobals());

const unconfirmed = {
  status: "types_unconfirmed",
  message: "Column types must be confirmed before a table is created.",
  columns: ["id", "clearance"],
  inferredTypes: ["int8", "text"],
  logs: [],
};

describe("uploadCsv sends the confirmation", () => {
  it("typesConfirmed defaults to false, so nothing is confirmed by omission", async () => {
    const m = mockFetchJson(unconfirmed);
    await uploadCsv({ fileName: "a.csv", content: "id\n1\n" });
    expect(sentBody(m).typesConfirmed).toBe(false);
  });

  it("sends typesConfirmed true with the confirmed types", async () => {
    const m = mockFetchJson(unconfirmed);
    await uploadCsv({
      fileName: "a.csv",
      content: "id\n1\n",
      types: ["text", "text"],
      typesConfirmed: true,
    });
    expect(sentBody(m)).toMatchObject({ typesConfirmed: true, types: ["text", "text"] });
  });
});

describe("response schema", () => {
  it("accepts types_unconfirmed and keeps the inferred types for display", async () => {
    mockFetchJson(unconfirmed);
    const res = await uploadCsv({ fileName: "a.csv", content: "x" });
    expect(res.status).toBe("types_unconfirmed");
    if (res.status !== "types_unconfirmed") throw new Error("unreachable");
    expect(res.inferredTypes).toEqual(["int8", "text"]);
  });

  it("accepts typesProvenance on a successful upload", async () => {
    mockFetchJson({
      status: "ok",
      fileId: "1",
      tableName: "csv_abc",
      totalRows: 1,
      insertedRows: 1,
      duplicateRowsSkipped: 0,
      failedRows: 0,
      columns: ["a"],
      types: ["text"],
      typesProvenance: "user_confirmed",
      rowErrors: [],
      logs: [],
    });
    const res = await uploadCsv({ fileName: "a.csv", content: "a\n1\n", typesConfirmed: true });
    expect(res.status === "ok" && res.typesProvenance).toBe("user_confirmed");
  });

  it("rejects a provenance value the API never sends", async () => {
    mockFetchJson({
      status: "ok",
      fileId: "1",
      tableName: "t",
      totalRows: 1,
      insertedRows: 1,
      duplicateRowsSkipped: 0,
      failedRows: 0,
      columns: ["a"],
      types: ["text"],
      typesProvenance: "guessed",
      rowErrors: [],
      logs: [],
    });
    await expect(uploadCsv({ fileName: "a.csv", content: "a" })).rejects.toThrow(
      /Unexpected response shape/,
    );
  });

  it("files list accepts both provenance values and null for T&E files", async () => {
    const base = {
      table_name: "t",
      row_count: 1,
      column_names: ["a"],
      created_at: "2026-11-09T00:00:00Z",
    };
    mockFetchJson([
      { id: "1", file_name: "a.csv", ...base, mode: "dynamic", types_provenance: "user_confirmed" },
      {
        id: "2",
        file_name: "b.csv",
        ...base,
        mode: "dynamic",
        types_provenance: "inferred_unconfirmed",
      },
      { id: "3", file_name: "c.csv", ...base, mode: "te", types_provenance: null },
      { id: "4", file_name: "d.csv", ...base }, // an older server that doesn't send it
    ]);
    const files = await listCsvFiles();
    expect(files.map((f) => f.types_provenance)).toEqual([
      "user_confirmed",
      "inferred_unconfirmed",
      null,
      undefined,
    ]);
  });
});

describe("classifyUploadResult for types_unconfirmed", () => {
  it("is a visible error, not a success and not a silent no-op", () => {
    const outcome = classifyUploadResult("a.csv", unconfirmed as never);
    expect(outcome.patch.status).toBe("error");
    expect(outcome.patch.errorMessage).toMatch(/confirmed/);
    expect(outcome.toast.type).toBe("error");
    expect(outcome.invalidateRoute).toBeFalsy();
  });
});
