import { describe, it, expect } from "vitest";
import { auditEventsQuery } from "@/lib/csv.functions";

describe("auditEventsQuery", () => {
  it("is empty with no filters", () => expect(auditEventsQuery({})).toBe(""));
  it("leaves out blank filters and trims the rest", () =>
    expect(auditEventsQuery({ actor: " ada ", action: "", file: "  " })).toBe("?actor=ada"));
  it("adds paging and format after the filters", () =>
    expect(auditEventsQuery({ action: "import" }, { limit: "50", format: "csv" })).toBe(
      "?action=import&limit=50&format=csv",
    ));
  it("encodes values", () =>
    expect(auditEventsQuery({ file: "a b&c.csv" })).toBe("?file=a+b%26c.csv"));
});
