// M3c (#107): the Migrated files Preview shows why rows failed, read from the server.

import { afterEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StoredRowErrors } from "@/routes/_authenticated/index";

const detail = {
  id: "7",
  status: "partly_imported",
  fileName: "people.csv",
  uploader: "alice",
  failedRows: 1,
  rowErrors: [{ rowNumber: 2, column: "n", value: "x", reason: '"x" is not a whole number' }],
  logs: [],
};

function show(body: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } }),
    );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StoredRowErrors uploadId="7" fileName="people.csv" />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

it("lists the stored reasons from the upload's server record", async () => {
  const fetchMock = show(detail);
  expect(await screen.findByText('"x" is not a whole number')).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /error report/i })).toBeInTheDocument();
  expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/csv\/uploads\/7$/);
});

it("says so when no reasons were stored", async () => {
  show({ ...detail, rowErrors: [] });
  expect(await screen.findByText(/no failure reasons were stored/i)).toBeInTheDocument();
});
