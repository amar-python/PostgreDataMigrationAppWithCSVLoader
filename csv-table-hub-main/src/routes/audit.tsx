import { createFileRoute, Link } from "@tanstack/react-router";
import { AUDIT_LOG } from "@/lib/audit-log";

export const Route = createFileRoute("/audit")({
  head: () => ({
    meta: [
      { title: "Audit log — CSV Migrator" },
      {
        name: "description",
        content:
          "Chronological record of changes shipped to the CSV Migrator app.",
      },
    ],
  }),
  component: AuditPage,
});

function AuditPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Chronological record of changes shipped to this app.
          </p>
        </div>
        <Link
          to="/"
          className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
        >
          Back to app
        </Link>
      </div>

      <ol className="space-y-6">
        {AUDIT_LOG.map((entry, i) => (
          <li
            key={i}
            className="rounded-lg border border-border bg-card p-5 shadow-sm"
          >
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="text-base font-semibold text-foreground">
                {entry.title}
              </h2>
              <time className="shrink-0 text-xs text-muted-foreground">
                {entry.date}
              </time>
            </div>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
              {entry.changes.map((c, j) => (
                <li key={j}>{c}</li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </div>
  );
}
