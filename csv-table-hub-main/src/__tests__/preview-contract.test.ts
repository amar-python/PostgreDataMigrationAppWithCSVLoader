// Regression tests for issue #42: the frontend must accept every response
// shape /api/csv/preview can return — including reason "parse_failed", which
// the API sends (with a message) when its CSV parser throws.
import { afterEach, describe, expect, it, vi } from "vitest";
import { previewCsv } from "@/lib/csv.functions";

function mockFetchJson(payload: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("previewCsv response contract (issue #42)", () => {
  it("accepts reason parse_failed and keeps the server message", async () => {
    const message = "The CSV couldn't be parsed. Check the file's structure and try again.";
    mockFetchJson({ status: "invalid_structure", reason: "parse_failed", message });

    const result = await previewCsv("broken.csv", "a\n1\n");

    expect(result.status).toBe("invalid_structure");
    if (result.status !== "invalid_structure") throw new Error("unreachable");
    expect(result.reason).toBe("parse_failed");
    expect(result.message).toBe(message);
  });

  it.each(["empty", "header_only", "no_columns"] as const)(
    "still accepts reason %s without a message",
    async (reason) => {
      mockFetchJson({ status: "invalid_structure", reason });
      await expect(previewCsv("f.csv", "x")).resolves.toEqual({ status: "invalid_structure", reason });
    },
  );

  it("still rejects a reason the API never sends", async () => {
    mockFetchJson({ status: "invalid_structure", reason: "not_a_reason" });
    await expect(previewCsv("f.csv", "x")).rejects.toThrow(/Unexpected response shape/);
  });

  it("posts fileName and content to /api/csv/preview", async () => {
    const fetchMock = mockFetchJson({ status: "invalid_structure", reason: "empty" });
    await previewCsv("f.csv", "a\n");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/csv\/preview$/);
    expect(JSON.parse(init.body)).toEqual({ fileName: "f.csv", content: "a\n" });
  });
});
