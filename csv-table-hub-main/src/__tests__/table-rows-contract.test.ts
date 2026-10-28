// The table rows response is parsed with z.record, whose signature changed in zod 4 (#132).
import { afterEach, expect, it, vi } from "vitest";
import { previewCsvTable } from "@/lib/csv.functions";

function mockFetchJson(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } }),
      ),
  );
}

afterEach(() => vi.unstubAllGlobals());

it("accepts rows of string, number, boolean and null cells", async () => {
  const rows = [{ name: "a", n: 1, ok: true, gone: null }];
  mockFetchJson({ rows });
  await expect(previewCsvTable("t")).resolves.toEqual({ rows });
});

it("rejects a row cell that is not a scalar", async () => {
  mockFetchJson({ rows: [{ nested: { x: 1 } }] });
  await expect(previewCsvTable("t")).rejects.toThrow(/Unexpected response shape/);
});
