// M4 (#108): review every stored row of an upload: page through it, include or
// exclude rows, edit cells (each edit is a new version) and see a row's history.
// Changes are recorded for review; they don't change the imported table.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  decideRow,
  editCell,
  getReviewPage,
  rowHistory,
  type ReviewPage,
  type ReviewRow,
} from "@/lib/csv.functions";
import { getSession } from "@/lib/session";
import { formatLocalTime } from "@/lib/utils";

export const PAGE_SIZE = 100;
const REVIEWERS = new Set(["reviewer", "tenant_admin"]);

type Change =
  | { kind: "decision"; row: ReviewRow; decision: "include" | "exclude" }
  | { kind: "edit"; row: ReviewRow; column: number };

export function ReviewTable({ uploadId }: { uploadId: string }) {
  const [page, setPage] = useState(0);
  const [change, setChange] = useState<Change | null>(null);
  const [historyRow, setHistoryRow] = useState<number | null>(null);
  const canReview = REVIEWERS.has(getSession()?.role ?? "");
  const queryClient = useQueryClient();
  const key = ["review", uploadId, page];
  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => getReviewPage(uploadId, page * PAGE_SIZE, PAGE_SIZE),
  });

  if (isLoading)
    return (
      <p className="flex items-center gap-2 py-12 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading rows…
      </p>
    );
  if (error || !data)
    return <p className="text-sm text-destructive">{(error as Error)?.message}</p>;

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const saved = (row: ReviewRow) => {
    queryClient.setQueryData<ReviewPage>(key, (old) =>
      old ? { ...old, rows: old.rows.map((r) => (r.rowNumber === row.rowNumber ? row : r)) } : old,
    );
    void queryClient.invalidateQueries({ queryKey: ["review", uploadId] });
    setChange(null);
  };

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{data.fileName}</h2>
      <p className="text-sm text-muted-foreground">
        {data.total} row{data.total === 1 ? "" : "s"} · {data.excludedRows} excluded ·{" "}
        {data.editedRows} edited. Changes are saved with the upload for review. They don't change
        the imported table.
        {!canReview && " Only reviewers and tenant admins can make changes."}
      </p>
      <div className="overflow-auto rounded border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-right">Row</TableHead>
              {data.columns.map((c, i) => (
                <TableHead key={c}>
                  {c} <span className="text-[10px] text-muted-foreground">{data.types[i]}</span>
                </TableHead>
              ))}
              <TableHead>Status</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.rows.map((row) => (
              <ReviewLine
                key={row.rowNumber}
                row={row}
                columns={data.columns}
                canReview={canReview}
                onChange={setChange}
                onHistory={() => setHistoryRow(row.rowNumber)}
              />
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-end gap-2 text-sm">
        <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
          Previous
        </Button>
        <span>
          Page {page + 1} of {pages}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={page + 1 >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
      {change && (
        <ChangeDialog
          uploadId={uploadId}
          change={change}
          columns={data.columns}
          onCancel={() => setChange(null)}
          onSaved={saved}
        />
      )}
      {historyRow !== null && (
        <HistoryDialog
          uploadId={uploadId}
          rowNumber={historyRow}
          onClose={() => setHistoryRow(null)}
        />
      )}
    </div>
  );
}

function ReviewLine({
  row,
  columns,
  canReview,
  onChange,
  onHistory,
}: {
  row: ReviewRow;
  columns: string[];
  canReview: boolean;
  onChange: (c: Change) => void;
  onHistory: () => void;
}) {
  const excluded = row.decision === "exclude";
  const errorFor = (name: string) => row.errors.find((e) => e.column === name);
  const extra = errorFor("(beyond header)");
  return (
    <TableRow className={excluded ? "opacity-50" : undefined}>
      <TableCell className="text-right tabular-nums text-xs text-muted-foreground">
        {row.rowNumber}
      </TableCell>
      {columns.map((name, i) => {
        const err = errorFor(name);
        const edited = row.editedColumns.includes(i);
        const title = [err?.reason, edited ? `Original: ${row.original[i]}` : ""]
          .filter(Boolean)
          .join(" · ");
        return (
          <TableCell
            key={name}
            title={title || undefined}
            className={`max-w-xs truncate ${edited ? "bg-blue-500/10" : ""} ${err ? "text-destructive" : ""}`}
          >
            {canReview ? (
              <button
                type="button"
                className="w-full text-left hover:underline"
                aria-label={`Edit row ${row.rowNumber} ${name}`}
                onClick={() => onChange({ kind: "edit", row, column: i })}
              >
                {row.current[i] || " "}
              </button>
            ) : (
              row.current[i]
            )}
          </TableCell>
        );
      })}
      <TableCell>
        <Badge variant={excluded ? "secondary" : "outline"} title={row.decisionReason ?? undefined}>
          {excluded ? "Excluded" : row.errors.length ? "Invalid" : "Included"}
        </Badge>
        {extra && <span className="block text-xs text-destructive">{extra.reason}</span>}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {canReview && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7"
            onClick={() =>
              onChange({ kind: "decision", row, decision: excluded ? "include" : "exclude" })
            }
          >
            {excluded ? "Include" : "Exclude"}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="h-7"
          aria-label={`History of row ${row.rowNumber}`}
          onClick={onHistory}
        >
          <History className="h-3.5 w-3.5" />
        </Button>
      </TableCell>
    </TableRow>
  );
}

function ChangeDialog({
  uploadId,
  change,
  columns,
  onCancel,
  onSaved,
}: {
  uploadId: string;
  change: Change;
  columns: string[];
  onCancel: () => void;
  onSaved: (row: ReviewRow) => void;
}) {
  const isEdit = change.kind === "edit";
  const [value, setValue] = useState(isEdit ? change.row.current[change.column] : "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const title = isEdit
    ? `Edit row ${change.row.rowNumber}, ${columns[change.column]}`
    : `${change.decision === "exclude" ? "Exclude" : "Include"} row ${change.row.rowNumber}`;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const row = isEdit
        ? await editCell(uploadId, change.row.rowNumber, columns[change.column], value, reason)
        : await decideRow(uploadId, change.row.rowNumber, change.decision, reason);
      onSaved(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {isEdit && (
              <DialogDescription>
                Original value: {change.row.original[change.column] || "(empty)"}
              </DialogDescription>
            )}
          </DialogHeader>
          {isEdit && (
            <div className="space-y-2">
              <Label htmlFor="review-value">New value</Label>
              <Input id="review-value" value={value} onChange={(e) => setValue(e.target.value)} />
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="review-reason">Reason</Label>
            <Input
              id="review-reason"
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !reason.trim()}>
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function HistoryDialog({
  uploadId,
  rowNumber,
  onClose,
}: {
  uploadId: string;
  rowNumber: number;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["review-history", uploadId, rowNumber],
    queryFn: () => rowHistory(uploadId, rowNumber),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>History of row {rowNumber}</DialogTitle>
        </DialogHeader>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">No changes yet.</p>
        )}
        <ul className="space-y-2 text-sm">
          {data?.map((h, i) => (
            <li key={i} className="rounded border p-2">
              <span className="font-medium">
                {h.kind === "decision"
                  ? h.decision === "exclude"
                    ? "Excluded"
                    : "Included"
                  : `${h.column}: "${h.oldValue}" → "${h.newValue}"`}
              </span>
              <span className="block text-xs text-muted-foreground">
                {h.actor ?? "unknown"} · <time dateTime={h.at}>{formatLocalTime(h.at)}</time> ·{" "}
                {h.reason}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
