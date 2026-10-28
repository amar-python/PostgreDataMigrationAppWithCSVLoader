// M4 (#108): the review screen — rows, validation, decisions and edits.

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReviewTable } from "@/components/review-table";
import { clearSession } from "@/lib/session";

const row = (n: number, cells: string[], extra: object = {}) => ({
  rowNumber: n,
  original: cells,
  current: cells,
  editedColumns: [],
  decision: "include",
  decisionReason: null,
  errors: [],
  ...extra,
});

const page = {
  fileName: "people.csv",
  columns: ["n", "t"],
  types: ["int8", "text"],
  total: 3,
  offset: 0,
  limit: 100,
  excludedRows: 1,
  editedRows: 1,
  rows: [
    row(1, ["1", "a"], { current: ["10", "a"], editedColumns: [0] }),
    row(2, ["x", "b"], {
      errors: [{ column: "n", value: "x", reason: '"x" is not a whole number' }],
    }),
    row(3, ["3", "c"], { decision: "exclude", decisionReason: "duplicate of row 1" }),
  ],
};

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });

function show(role: string) {
  sessionStorage.setItem(
    "te.session",
    JSON.stringify({
      token: "t",
      expiresAt: "2099-01-01T00:00:00Z",
      username: "u",
      tenant: "acme",
      role,
    }),
  );
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
    init?.method === "PUT"
      ? json(row(2, ["x", "b"], { decision: "exclude", decisionReason: "bad row" }))
      : json(page),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReviewTable uploadId="7" />
    </QueryClientProvider>,
  );
  return fetchMock;
}

beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

it("shows every row with its validation, edits and decision", async () => {
  show("reviewer");
  expect(await screen.findByText("people.csv")).toBeInTheDocument();
  expect(screen.getByText(/3 rows · 1 excluded · 1 edited/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit row 1 n" }).closest("td")).toHaveAttribute(
    "title",
    "Original: 1",
  );
  expect(screen.getByRole("button", { name: "Edit row 2 n" }).closest("td")).toHaveAttribute(
    "title",
    '"x" is not a whole number',
  );
  expect(screen.getByText("Invalid")).toBeInTheDocument();
  expect(screen.getByText("Excluded")).toHaveAttribute("title", "duplicate of row 1");
});

it("a reviewer excludes a row with a required reason", async () => {
  const fetchMock = show("reviewer");
  const user = userEvent.setup();
  const line = (await screen.findByRole("button", { name: "Edit row 2 n" })).closest("tr")!;
  await user.click(within(line as HTMLElement).getByRole("button", { name: "Exclude" }));
  const save = screen.getByRole("button", { name: "Save" });
  expect(save).toBeDisabled();
  await user.type(screen.getByLabelText("Reason"), "bad row");
  await user.click(save);
  const [url, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
  expect(String(url)).toMatch(/\/api\/csv\/uploads\/7\/rows\/2\/decision$/);
  expect(JSON.parse(String(init!.body))).toEqual({ decision: "exclude", reason: "bad row" });
});

it("a reviewer edits a cell as a new value with a reason", async () => {
  const fetchMock = show("tenant_admin");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit row 2 n" }));
  expect(screen.getByText("Original value: x")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("New value"));
  await user.type(screen.getByLabelText("New value"), "2");
  await user.type(screen.getByLabelText("Reason"), "typo");
  await user.click(screen.getByRole("button", { name: "Save" }));
  const [url, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
  expect(String(url)).toMatch(/\/rows\/2\/cells\/n$/);
  expect(JSON.parse(String(init!.body))).toEqual({ value: "2", reason: "typo" });
});

it("other roles can view but not change", async () => {
  show("uploader");
  expect(
    await screen.findByText(/Only reviewers and tenant admins can make changes/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Exclude" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Edit row 1 n" })).toBeNull();
});
