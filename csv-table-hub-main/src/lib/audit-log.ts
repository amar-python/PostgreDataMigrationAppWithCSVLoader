export type AuditEntry = {
  date: string; // ISO date
  title: string;
  changes: string[];
};

// Newest first. Append a new entry at the top when shipping changes.
export const AUDIT_LOG: AuditEntry[] = [
  {
    date: "2026-07-21",
    title: "Preview dialog scroll & SSR timestamp fix",
    changes: [
      "Fixed page crash on load caused by a server/client timestamp mismatch — timestamps now render as a stable UTC string.",
      "File preview dialog is now capped at 90vh with internal scrolling so all preview rows are reachable.",
      "Added this in-app audit log at /audit so past changes are easy to review.",
    ],
  },
  {
    date: "2026-07-21",
    title: "Diagnostics, processing logs, stricter validation, E2E tests",
    changes: [
      "Added a diagnostics panel showing per-step status counts and recent warnings/errors across the current batch.",
      "Instrumented uploadCsv with per-step processing logs (hash, parse, validate, create table, cast, insert) exportable as JSON.",
      "Stricter server-side validation: sanitized/validated column identifiers, duplicate-column detection, and in-file row-hash duplicate detection.",
      "Added scripts/e2e-csv.sh with fixtures (including an ambiguous-header case) to catch regressions like the earlier PL/pgSQL variable collision.",
    ],
  },
  {
    date: "2026-07-21",
    title: "Ambiguous column reference fix",
    changes: [
      "Renamed PL/pgSQL loop variables in create_csv_table (i → idx, s) to remove the 'column reference \"i\" is ambiguous' error during table creation.",
    ],
  },
];
