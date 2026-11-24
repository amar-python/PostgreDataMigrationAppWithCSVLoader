import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AUDIT_ACTIONS,
  downloadAuditEventsCsv,
  listAuditEvents,
  type AuditFilters,
} from "@/lib/csv.functions";

const nextDay = (d: string) => new Date(new Date(d).getTime() + 86400000).toISOString();

/** The server's audit log, filtered by actor, action, file and date (BR-35). Needs the read_audit permission. */
export function ServerAuditEvents() {
  const [form, setForm] = useState({ actor: "", action: "", file: "", from: "", to: "" });
  const [applied, setApplied] = useState<AuditFilters>({});
  const [offset, setOffset] = useState(0);

  const query = useQuery({
    queryKey: ["audit-events", applied, offset],
    queryFn: () => listAuditEvents(applied, offset),
  });

  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setApplied({
      actor: form.actor,
      action: form.action,
      file: form.file,
      from: form.from ? new Date(form.from).toISOString() : "",
      to: form.to ? nextDay(form.to) : "",
    });
  };
  const set =
    (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));
  const page = query.data;

  return (
    <section aria-label="Server audit events" className="space-y-3">
      <form onSubmit={apply} className="flex flex-wrap items-end gap-2">
        <label className="text-xs">
          Actor
          <Input value={form.actor} onChange={set("actor")} className="h-8 w-36" />
        </label>
        <label className="text-xs">
          Action
          <select
            value={form.action}
            onChange={set("action")}
            className="block h-8 rounded-md border bg-background px-2 text-sm"
          >
            <option value="">All</option>
            {AUDIT_ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          File
          <Input value={form.file} onChange={set("file")} className="h-8 w-40" />
        </label>
        <label className="text-xs">
          From
          <Input type="date" value={form.from} onChange={set("from")} className="h-8" />
        </label>
        <label className="text-xs">
          To
          <Input type="date" value={form.to} onChange={set("to")} className="h-8" />
        </label>
        <Button type="submit" size="sm">
          Apply
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => downloadAuditEventsCsv(applied).catch((e) => toast.error(e.message))}
        >
          Download CSV
        </Button>
      </form>

      {query.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(query.error as Error).message}
        </p>
      )}
      {page && (
        <>
          <p className="text-xs">
            {page.total} event{page.total === 1 ? "" : "s"} · {page.classification}
          </p>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When (UTC)</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>File</TableHead>
                  <TableHead>Table</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {page.entries.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="text-xs">{e.performedAt}</TableCell>
                    <TableCell className="text-xs">{e.actor ?? "—"}</TableCell>
                    <TableCell className="text-xs">{e.action}</TableCell>
                    <TableCell className="text-xs">{e.fileName ?? "—"}</TableCell>
                    <TableCell className="text-xs">{e.tableName ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - page.limit))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={offset + page.limit >= page.total}
              onClick={() => setOffset(offset + page.limit)}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
