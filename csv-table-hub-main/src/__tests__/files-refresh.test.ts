// src/__tests__/files-refresh.test.ts
// Regression test for #64: after an upload, router.invalidate() re-runs the
// home route loader. The loader must refetch the files list rather than hand
// back the cached one, or the new file only appears after navigating away.

import { describe, it, expect, vi, afterEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { filesQuery, uploadsQuery, loadFiles } from "@/lib/csv.functions";

const file = (name: string) => ({
  id: name,
  file_name: name,
  table_name: `csv_${name}`,
  row_count: 1,
  column_names: ["a"],
  created_at: "2026-10-26T00:00:00Z",
});

afterEach(() => vi.unstubAllGlobals());

const attempt = (id: string, status: string) => ({
  id,
  file_name: `${id}.csv`,
  mode: "dynamic",
  status,
  total_rows: 3,
  imported_rows: 0,
  failed_rows: 3,
  uploaded_at: "2026-10-26T00:00:00Z",
});

describe("loadFiles", () => {
  it("refetches the files list and the upload attempts when the loader re-runs", async () => {
    const files = [[file("a")], [file("a"), file("b")]];
    const uploads = [[], [attempt("7", "failed")]];
    const fetchMock = vi.fn(async (url: string) =>
      new Response(JSON.stringify(String(url).includes("/uploads") ? uploads.shift() : files.shift())),
    );
    vi.stubGlobal("fetch", fetchMock);
    const qc = new QueryClient();

    await loadFiles(qc); // first page load
    await loadFiles(qc); // router.invalidate() after an upload

    // #187: an all-failed upload has no migrated file, so it must come from the attempts list.
    await vi.waitFor(() => expect(qc.getQueryData(filesQuery.queryKey)).toHaveLength(2));
    await vi.waitFor(() => expect(qc.getQueryData(uploadsQuery.queryKey)).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
