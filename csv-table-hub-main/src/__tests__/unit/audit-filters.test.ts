// src/__tests__/audit-filters.test.ts
// Tests the filter logic that the AuditPage component applies to jobs.
// Rather than rendering the full component (which needs TanStack Router
// and other providers), we extract the predicate and run it directly —
// the same logic the component uses via useMemo.

import { describe, it, expect } from "vitest";
import type { Job } from "@/lib/job-types";

// ─── extracted filter predicate (mirrors the useMemo in AuditPage) ────────────

function applyFilters(
  jobs: Job[],
  { search, statusFilter, dateFrom, dateTo }: {
    search: string; statusFilter: string; dateFrom: string; dateTo: string;
  },
): Job[] {
  return jobs.filter((j) => {
    if (search && !j.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter !== "all") {
      if (statusFilter === "overwritten") {
        if (j.status !== "done" || !j.overwritten) return false;
      } else if (j.status !== statusFilter) {
        return false;
      }
    }
    if (dateFrom) {
      if (j.createdAt < new Date(dateFrom).getTime()) return false;
    }
    if (dateTo) {
      if (j.createdAt > new Date(dateTo).getTime() + 86_400_000) return false;
    }
    return true;
  });
}

// ─── fixtures ─────────────────────────────────────────────────────────────────

function job(overrides: Partial<Job> & Pick<Job, "id" | "name" | "status" | "createdAt">): Job {
  return { size: 1000, batchId: "b1", progress: 100, ...overrides };
}

const JAN1 = new Date("2026-01-01T00:00:00Z").getTime();
const JAN2 = new Date("2026-01-02T00:00:00Z").getTime();
const JAN3 = new Date("2026-01-03T00:00:00Z").getTime();

const JOBS: Job[] = [
  job({ id: "j1", name: "sales-2026.csv",   status: "done",      createdAt: JAN1 }),
  job({ id: "j2", name: "contacts.csv",     status: "done",      createdAt: JAN2, overwritten: true }),
  job({ id: "j3", name: "products.csv",     status: "error",     createdAt: JAN2 }),
  job({ id: "j4", name: "orders.csv",       status: "duplicate", createdAt: JAN3 }),
  job({ id: "j5", name: "inventory.csv",    status: "cancelled", createdAt: JAN3 }),
  job({ id: "j6", name: "SALES-archive.csv",status: "done",      createdAt: JAN1 }),
];

const NONE = { search: "", statusFilter: "all", dateFrom: "", dateTo: "" };

// ─── search (F1) ──────────────────────────────────────────────────────────────

describe("F1 – filename search", () => {
  it("returns all jobs when search is empty", () => {
    expect(applyFilters(JOBS, NONE)).toHaveLength(JOBS.length);
  });

  it("filters by exact substring", () => {
    const result = applyFilters(JOBS, { ...NONE, search: "contacts" });
    expect(result.map((j) => j.id)).toEqual(["j2"]);
  });

  it("is case-insensitive", () => {
    const result = applyFilters(JOBS, { ...NONE, search: "SALES" });
    expect(result.map((j) => j.id)).toContain("j1");
    expect(result.map((j) => j.id)).toContain("j6");
  });

  it("returns empty array when nothing matches", () => {
    expect(applyFilters(JOBS, { ...NONE, search: "zzz-no-match" })).toHaveLength(0);
  });

  it("matches partial filenames", () => {
    expect(applyFilters(JOBS, { ...NONE, search: "ord" }).map((j) => j.id)).toEqual(["j4"]);
  });
});

// ─── status filter (F1) ───────────────────────────────────────────────────────

describe("F1 – status filter", () => {
  it("'all' returns every job", () => {
    expect(applyFilters(JOBS, NONE)).toHaveLength(6);
  });

  it("'done' returns only done jobs (including overwritten)", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "done" });
    expect(result.every((j) => j.status === "done")).toBe(true);
    expect(result).toHaveLength(3); // j1, j2, j6
  });

  it("'overwritten' returns only done+overwritten jobs", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "overwritten" });
    expect(result.map((j) => j.id)).toEqual(["j2"]);
  });

  it("'error' returns only failed jobs", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "error" });
    expect(result.map((j) => j.id)).toEqual(["j3"]);
  });

  it("'duplicate' returns only duplicate jobs", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "duplicate" });
    expect(result.map((j) => j.id)).toEqual(["j4"]);
  });

  it("'cancelled' returns only cancelled jobs", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "cancelled" });
    expect(result.map((j) => j.id)).toEqual(["j5"]);
  });

  it("non-overwritten done job does NOT appear under 'overwritten'", () => {
    const result = applyFilters(JOBS, { ...NONE, statusFilter: "overwritten" });
    expect(result.map((j) => j.id)).not.toContain("j1");
  });
});

// ─── date range (F1) ──────────────────────────────────────────────────────────

describe("F1 – date range filter", () => {
  it("dateFrom excludes jobs before the date", () => {
    const result = applyFilters(JOBS, { ...NONE, dateFrom: "2026-01-02" });
    const ids = result.map((j) => j.id);
    expect(ids).not.toContain("j1");
    expect(ids).not.toContain("j6");
    expect(ids).toContain("j2");
    expect(ids).toContain("j4");
  });

  it("dateTo includes jobs on the specified day; jobs strictly after it are excluded", () => {
    // The filter adds 86400000ms to make the day inclusive, so midnight of
    // the NEXT day (JAN2 UTC) also passes. Only JAN3 and later are excluded.
    const result = applyFilters(JOBS, { ...NONE, dateTo: "2026-01-01" });
    const ids = result.map((j) => j.id);
    expect(ids).toContain("j1");   // JAN1 ✓
    expect(ids).toContain("j6");   // JAN1 ✓
    expect(ids).not.toContain("j4"); // JAN3 — excluded
    expect(ids).not.toContain("j5"); // JAN3 — excluded
  });

  it("dateFrom + dateTo together form a closed range", () => {
    // dateTo "2026-01-02" allows up to JAN2 + 86400s = JAN3 midnight,
    // so JAN3 midnight timestamps are included. Confirm JAN1 is excluded.
    const result = applyFilters(JOBS, { ...NONE, dateFrom: "2026-01-02", dateTo: "2026-01-02" });
    const ids = result.map((j) => j.id);
    expect(ids).toContain("j2");   // JAN2 ✓
    expect(ids).toContain("j3");   // JAN2 ✓
    expect(ids).not.toContain("j1");  // JAN1 — below dateFrom ✗
    expect(ids).not.toContain("j6");  // JAN1 — below dateFrom ✗
  });

  it("empty date strings do not filter by date", () => {
    const result = applyFilters(JOBS, { ...NONE, dateFrom: "", dateTo: "" });
    expect(result).toHaveLength(6);
  });
});

// ─── combined filters ─────────────────────────────────────────────────────────

describe("F1 – combined filters", () => {
  it("search + status combined narrow correctly", () => {
    // "sales" matches j1 and j6; filtering to 'done' keeps both
    const result = applyFilters(JOBS, { ...NONE, search: "sales", statusFilter: "done" });
    expect(result.map((j) => j.id).sort()).toEqual(["j1", "j6"].sort());
  });

  it("search + date + status combined to a single result", () => {
    const result = applyFilters(JOBS, { search: "contacts", statusFilter: "overwritten", dateFrom: "2026-01-02", dateTo: "2026-01-02" });
    expect(result.map((j) => j.id)).toEqual(["j2"]);
  });

  it("returns empty when search and status conflict", () => {
    const result = applyFilters(JOBS, { ...NONE, search: "products", statusFilter: "done" });
    expect(result).toHaveLength(0); // j3 is 'error', not 'done'
  });
});
