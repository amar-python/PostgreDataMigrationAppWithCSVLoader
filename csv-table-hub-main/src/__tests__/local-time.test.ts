// src/__tests__/local-time.test.ts — upload times in the viewer's time zone (#119).
import { describe, it, expect } from "vitest";
import { formatLocalTime, formatUtc } from "@/lib/utils";

describe("formatLocalTime", () => {
  it("shows the #119 upload in Sydney time, not UTC", () => {
    // Uploaded 27 Oct 2026 19:33 AEDT, stored as 08:33 UTC.
    expect(formatLocalTime("2026-10-27T08:33:00Z", "Australia/Sydney")).toBe("27 Oct 2026, 19:33");
  });

  it("crosses midnight correctly", () => {
    expect(formatLocalTime("2026-10-26T15:16:00Z", "Australia/Sydney")).toBe("27 Oct 2026, 02:16");
  });

  it("uses each viewer's own zone", () => {
    expect(formatLocalTime("2026-10-27T08:33:00Z", "Europe/London")).toBe("27 Oct 2026, 08:33");
  });

  it("accepts epoch milliseconds (import history)", () => {
    expect(formatLocalTime(Date.UTC(2026, 9, 27, 8, 33), "Australia/Sydney")).toBe(
      "27 Oct 2026, 19:33",
    );
  });
});

describe("formatUtc (tooltip)", () => {
  it("keeps the exact UTC time for audit", () => {
    expect(formatUtc("2026-10-27T08:33:05.123Z")).toBe("2026-10-27 08:33:05 UTC");
  });
});
