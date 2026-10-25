// src/__tests__/files-refresh.test.ts
// Regression test for #64: after an upload, router.invalidate() re-runs the
// home route loader. The loader must refetch the files list rather than hand
// back the cached one, or the new file only appears after navigating away.

import { describe, it, expect, vi, afterEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { filesQuery, loadFiles } from "@/lib/csv.functions";

const file = (name: string) => ({
  id: name,
  file_name: name,
  table_name: `csv_${name}`,
  row_count: 1,
  column_names: ["a"],
  created_at: "2026-10-26T00:00:00Z",
});

afterEach(() => vi.unstubAllGlobals());

describe("loadFiles", () => {
  it("refetches the files list when the loader re-runs", async () => {
    const responses = [[file("a")], [file("a"), file("b")]];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(responses.shift())));
    vi.stubGlobal("fetch", fetchMock);
    const qc = new QueryClient();

    await loadFiles(qc); // first page load
    await loadFiles(qc); // router.invalidate() after an upload

    await vi.waitFor(() => expect(qc.getQueryData(filesQuery.queryKey)).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
