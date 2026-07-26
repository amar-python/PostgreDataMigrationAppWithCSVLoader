import { createFileRoute, Link, useNavigate, useRouter } from "@tanstack/react-router";
import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  listCsvFiles,
  previewCsvTable,
  uploadCsv,
  type CsvFileSummary,
  type UploadResult,
  type RowError,
  type ColumnType,
  type ProcessingLog,
} from "@/lib/csv.functions";
import { parseCsvPreview, COLUMN_TYPE_LABEL, type CsvPreview } from "@/lib/csv-preview";
import { useLocalStorageState } from "@/hooks/use-local-storage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { toast, Toaster } from "sonner";
import {
  Loader2,
  UploadCloud,
  FileSpreadsheet,
  Database,
  Eye,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RotateCw,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  PauseCircle,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

const filesQuery = {
  queryKey: ["csv-files"],
  queryFn: () => listCsvFiles(),
};

export const Route = createFileRoute("/_authenticated/")({
  head: () => ({
    meta: [
      { title: "CSV Migrator — Upload CSV files to your database" },
      {
        name: "description",
        content:
          "Upload any number of CSV files. Each becomes its own database table, with duplicates automatically skipped.",
      },
      { property: "og:title", content: "CSV Migrator" },
      {
        property: "og:description",
        content: "Turn CSV files into database tables with automatic de-duplication.",
      },
    ],
  }),
  loader: ({ context }) => context.queryClient.ensureQueryData(filesQuery),
  component: Home,
});

function Home() {
  const { data: files } = useSuspenseQuery(filesQuery);
  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/30">
      <Toaster richColors position="top-right" />
      <header className="border-b bg-card/40 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">CSV Migrator</h1>
              <p className="text-xs text-muted-foreground">
                CSV in, database tables out — no duplicates.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="secondary" className="hidden sm:inline-flex">
              {files.length} file{files.length === 1 ? "" : "s"} migrated
            </Badge>
            <Link
              to="/audit"
              className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Audit log
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-8 px-6 py-10">
        <Uploader />
        <FilesList files={files} />
      </main>
    </div>
  );
}



type JobStatus =
  | "reading"
  | "uploading"
  | "processing"
  | "done"
  | "duplicate"
  | "error"
  | "interrupted";

type Job = {
  id: string;
  batchId: string;
  name: string;
  size: number;
  status: JobStatus;
  progress: number;
  createdAt: number;
  // Success/duplicate/error data
  insertedRows?: number;
  duplicateRowsSkipped?: number;
  failedRows?: number;
  totalRows?: number;
  tableName?: string;
  existingFileName?: string;
  duplicateReason?: "content" | "name" | "empty";
  invalidReason?: "empty" | "header_only" | "no_columns";
  existingRowCount?: number;
  overwritten?: boolean;
  replacedFileName?: string;
  errorMessage?: string;
  errorDetails?: string;
  errorStack?: string;
  rowErrors?: RowError[];
  columns?: string[];
  types?: ColumnType[];
  logs?: ProcessingLog[];
};

const STATUS_LABEL: Record<JobStatus, string> = {
  reading: "Reading file…",
  uploading: "Uploading…",
  processing: "Processing on server…",
  done: "Imported",
  duplicate: "Duplicate file",
  error: "Failed",
  interrupted: "Interrupted",
};

function readFileWithProgress(
  file: File,
  onProgress: (pct: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 60));
      }
    };
    reader.onerror = () =>
      reject(reader.error ?? new Error("Could not read the file."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(file);
  });
}

type PendingPreview = {
  file: File;
  preview: CsvPreview;
  batchId: string;
};

function Uploader() {
  const router = useRouter();
  const upload = uploadCsv;
  const [dragOver, setDragOver] = useState(false);
  const [jobs, setJobs, clearStoredJobs] = useLocalStorageState<Job[]>([]);
  const [pending, setPending] = useState<PendingPreview[]>([]);
  const [previewIndex, setPreviewIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  // File objects for retry (not persisted)
  const fileMap = useRef<Map<string, File>>(new Map());

  // On mount: mark any non-terminal persisted jobs as interrupted
  useEffect(() => {
    setJobs((prev) =>
      prev.map((j) =>
        ["reading", "uploading", "processing"].includes(j.status)
          ? { ...j, status: "interrupted", progress: 100 }
          : j,
      ),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = jobs.some((j) =>
    ["reading", "uploading", "processing"].includes(j.status),
  );

  const updateJob = useCallback(
    (id: string, patch: Partial<Job>) => {
      setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)));
    },
    [setJobs],
  );

  const runJob = useCallback(
    async (job: Job, file: File, types?: ColumnType[], overwrite?: boolean) => {
      try {
        updateJob(job.id, { status: "reading", progress: 5 });
        const content = await readFileWithProgress(file, (pct) =>
          updateJob(job.id, { progress: Math.max(5, pct) }),
        );
        updateJob(job.id, { status: "uploading", progress: 75 });
        await new Promise((r) => setTimeout(r, 30));
        updateJob(job.id, { status: "processing", progress: 90 });

        const res = (await upload({
          data: { fileName: job.name, content, types, overwrite },
        })) as UploadResult;

        if (res.status === "ok") {
          updateJob(job.id, {
            status: "done",
            progress: 100,
            insertedRows: res.insertedRows,
            duplicateRowsSkipped: res.duplicateRowsSkipped,
            failedRows: res.failedRows,
            totalRows: res.totalRows,
            tableName: res.tableName,
            columns: res.columns,
            types: res.types,
            rowErrors: res.rowErrors,
            logs: res.logs,
            overwritten: res.overwritten,
            replacedFileName: res.replacedFileName,
          });
          const prefix = res.overwritten ? "overwrote previous upload · " : "";
          toast.success(
            `${job.name}: ${prefix}${res.insertedRows} of ${res.totalRows} rows imported` +
              (res.duplicateRowsSkipped ? ` · ${res.duplicateRowsSkipped} duplicate rows skipped` : "") +
              (res.failedRows ? ` · ${res.failedRows} failed` : ""),
          );
          await router.invalidate();
        } else if (res.status === "duplicate_file") {
          updateJob(job.id, {
            status: "duplicate",
            progress: 100,
            existingFileName: res.existingFileName,
            tableName: res.tableName,
            duplicateReason: res.reason,
            existingRowCount: res.existingRowCount,
            logs: res.logs,
          });
          toast.warning(
            res.reason === "name"
              ? `${job.name}: a different file with this name is already imported — click Overwrite to replace it.`
              : `${job.name}: already imported${res.existingFileName ? ` as "${res.existingFileName}"` : ""} — skipped. Click Overwrite to replace.`,
          );
        } else if (res.status === "invalid_structure") {
          updateJob(job.id, {
            status: "error",
            progress: 100,
            errorMessage: res.message,
            errorDetails: res.message,
            invalidReason: res.reason,
            logs: res.logs,
          });
          toast.error(`${job.name}: ${res.message}`);
        } else {
          updateJob(job.id, {
            status: "error",
            progress: 100,
            errorMessage: res.message,
            errorDetails: res.message,
            rowErrors: res.rowErrors,
            logs: res.logs,
          });
          toast.error(`${job.name}: ${res.message}`);
        }
      } catch (err) {
        const e = err as Error;
        updateJob(job.id, {
          status: "error",
          progress: 100,
          errorMessage: e.message || "Unknown error",
          errorDetails: e.message,
          errorStack: e.stack,
        });
        toast.error(`${job.name}: ${e.message}`);
      }
    },
    [upload, router, updateJob],
  );

  const startBatch = useCallback(
    async (items: PendingPreview[]) => {
      // Create Job records for each; store files in ref map for retry
      const newJobs: Job[] = items.map((it) => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        fileMap.current.set(id, it.file);
        return {
          id,
          batchId: it.batchId,
          name: it.file.name,
          size: it.file.size,
          status: "reading",
          progress: 0,
          createdAt: Date.now(),
        };
      });
      setJobs((prev) => [...newJobs, ...prev]);
      for (let i = 0; i < items.length; i++) {
        await runJob(newJobs[i], items[i].file, items[i].preview.inferredTypes);
      }
    },
    [runJob, setJobs],
  );

  const handleFiles = useCallback(
    async (files: File[]) => {
      const csvs = files.filter(
        (f) => f.name.toLowerCase().endsWith(".csv") || f.type === "text/csv",
      );
      if (csvs.length === 0) {
        toast.error("Please drop .csv files.");
        return;
      }
      const batchId = `b-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const previews: PendingPreview[] = [];
      for (const f of csvs) {
        try {
          const p = await parseCsvPreview(f);
          previews.push({ file: f, preview: p, batchId });
        } catch (err) {
          toast.error(`${f.name}: ${(err as Error).message}`);
        }
      }
      if (previews.length === 0) return;
      setPending(previews);
      setPreviewIndex(0);
    },
    [],
  );

  const confirmAll = useCallback(async () => {
    const items = pending;
    setPending([]);
    setPreviewIndex(0);
    await startBatch(items);
  }, [pending, startBatch]);

  const cancelAll = useCallback(() => {
    setPending([]);
    setPreviewIndex(0);
    toast.info("Import cancelled.");
  }, []);

  const retryJob = useCallback(
    async (id: string, opts?: { overwrite?: boolean }) => {
      const job = jobs.find((j) => j.id === id);
      if (!job) return;
      const file = fileMap.current.get(id);
      if (!file) {
        toast.error("Original file no longer available — please re-select it.");
        return;
      }
      updateJob(id, {
        status: "reading",
        progress: 0,
        errorMessage: undefined,
        errorDetails: undefined,
        errorStack: undefined,
        rowErrors: undefined,
        invalidReason: undefined,
      });
      const preview = await parseCsvPreview(file);
      await runJob(job, file, preview.inferredTypes, opts?.overwrite);
    },
    [jobs, runJob, updateJob],
  );

  const clearFinished = useCallback(() => {
    setJobs((prev) => {
      const remaining = prev.filter(
        (j) => !["done", "duplicate", "error", "interrupted"].includes(j.status),
      );
      if (remaining.length === 0) clearStoredJobs();
      // clean file map for removed jobs
      const remainingIds = new Set(remaining.map((j) => j.id));
      for (const id of Array.from(fileMap.current.keys())) {
        if (!remainingIds.has(id)) fileMap.current.delete(id);
      }
      return remaining;
    });
  }, [setJobs, clearStoredJobs]);

  return (
    <div className="space-y-4">
      <Card className="border-dashed">
        <CardContent className="p-0">
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleFiles(Array.from(e.dataTransfer.files));
            }}
            className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg p-12 text-center transition-colors ${
              dragOver ? "bg-primary/5" : "hover:bg-muted/40"
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              multiple
              className="hidden"
              onChange={(e) => {
                const list = e.target.files ? Array.from(e.target.files) : [];
                if (list.length) handleFiles(list);
                if (inputRef.current) inputRef.current.value = "";
              }}
            />
            <div className="rounded-full bg-primary/10 p-4 text-primary">
              <UploadCloud className="h-8 w-8" />
            </div>
            <div>
              <p className="font-medium">Drop CSV files here or click to select</p>
              <p className="mt-1 text-sm text-muted-foreground">
                We'll show a preview of columns and detected types before importing.
              </p>
            </div>
            <Button type="button" onClick={() => inputRef.current?.click()}>
              Choose files
            </Button>
          </label>
        </CardContent>
      </Card>

      {jobs.length > 0 && (
        <UploadReport
          jobs={jobs}
          running={running}
          onRetry={retryJob}
          onOverwrite={(id) => retryJob(id, { overwrite: true })}
          onClearFinished={clearFinished}
        />
      )}

      <PreviewDialog
        pending={pending}
        index={previewIndex}
        onPrev={() => setPreviewIndex((i) => Math.max(0, i - 1))}
        onNext={() => setPreviewIndex((i) => Math.min(pending.length - 1, i + 1))}
        onConfirm={confirmAll}
        onCancel={cancelAll}
      />
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function StatusPill({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, { cls: string; icon: ReactNode }> = {
    reading: { cls: "bg-muted text-muted-foreground", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    uploading: { cls: "bg-muted text-muted-foreground", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    processing: { cls: "bg-muted text-muted-foreground", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    done: { cls: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400", icon: <CheckCircle2 className="h-3 w-3" /> },
    duplicate: { cls: "bg-amber-500/10 text-amber-700 dark:text-amber-400", icon: <AlertTriangle className="h-3 w-3" /> },
    error: { cls: "bg-destructive/10 text-destructive", icon: <XCircle className="h-3 w-3" /> },
    interrupted: { cls: "bg-slate-500/10 text-slate-600 dark:text-slate-400", icon: <PauseCircle className="h-3 w-3" /> },
  };
  const cfg = map[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.cls}`}>
      {cfg.icon}
      {STATUS_LABEL[status]}
    </span>
  );
}

function BatchSummary({ jobs }: { jobs: Job[] }) {
  // Group by batch, show most recent batch summary
  const byBatch = useMemo(() => {
    const map = new Map<string, Job[]>();
    for (const j of jobs) {
      const list = map.get(j.batchId) ?? [];
      list.push(j);
      map.set(j.batchId, list);
    }
    // sort batches by max createdAt desc
    return Array.from(map.entries()).sort((a, b) => {
      const am = Math.max(...a[1].map((j) => j.createdAt));
      const bm = Math.max(...b[1].map((j) => j.createdAt));
      return bm - am;
    });
  }, [jobs]);

  const [batchId] = byBatch[0] ?? [null];
  const batchJobs = batchId ? (byBatch[0]?.[1] ?? []) : [];
  if (!batchId) return null;

  const filesTotal = batchJobs.length;
  const rowsProcessed = batchJobs.reduce((s, j) => s + (j.totalRows ?? 0), 0);
  const rowsCreated = batchJobs.reduce((s, j) => s + (j.insertedRows ?? 0), 0);
  const dupRows = batchJobs.reduce((s, j) => s + (j.duplicateRowsSkipped ?? 0), 0);
  const failedRows = batchJobs.reduce((s, j) => s + (j.failedRows ?? 0), 0);
  const dupFiles = batchJobs.filter((j) => j.status === "duplicate").length;
  const failedFiles = batchJobs.filter((j) => j.status === "error").length;
  const inProgress = batchJobs.filter((j) => ["reading", "uploading", "processing"].includes(j.status)).length;

  const stat = (label: string, value: number, cls?: string) => (
    <div className="flex flex-col">
      <span className={`text-lg font-semibold tabular-nums ${cls ?? ""}`}>{value}</span>
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
    </div>
  );

  return (
    <div className="grid grid-cols-2 gap-4 rounded-lg border bg-muted/30 p-4 sm:grid-cols-4 lg:grid-cols-7">
      {stat("Files", filesTotal)}
      {stat("Rows processed", rowsProcessed)}
      {stat("Rows created", rowsCreated, "text-emerald-600 dark:text-emerald-400")}
      {stat("Duplicate rows", dupRows, "text-amber-600 dark:text-amber-400")}
      {stat("Failed rows", failedRows, failedRows ? "text-destructive" : "")}
      {stat("Duplicate files", dupFiles, dupFiles ? "text-amber-600 dark:text-amber-400" : "")}
      {stat("Failed files", failedFiles, failedFiles ? "text-destructive" : "")}
      {inProgress > 0 && (
        <div className="col-span-full text-xs text-muted-foreground">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
          {inProgress} file{inProgress === 1 ? "" : "s"} still processing…
        </div>
      )}
    </div>
  );
}

function DiagnosticsPanel({ jobs }: { jobs: Job[] }) {
  const [open, setOpen] = useState(false);

  const stepCounts = useMemo(() => {
    const counts: Record<string, { info: number; warn: number; error: number }> = {};
    for (const j of jobs) {
      for (const l of j.logs ?? []) {
        counts[l.step] ??= { info: 0, warn: 0, error: 0 };
        counts[l.step][l.level] += 1;
      }
    }
    return counts;
  }, [jobs]);

  const recentEvents = useMemo(() => {
    const events: (ProcessingLog & { file: string })[] = [];
    for (const j of jobs) {
      for (const l of j.logs ?? []) {
        if (l.level === "warn" || l.level === "error") {
          events.push({ ...l, file: j.name });
        }
      }
    }
    return events.sort((a, b) => b.ts - a.ts).slice(0, 20);
  }, [jobs]);

  const totalErrors = Object.values(stepCounts).reduce((s, c) => s + c.error, 0);
  const totalWarns = Object.values(stepCounts).reduce((s, c) => s + c.warn, 0);
  const stepEntries = Object.entries(stepCounts);

  if (stepEntries.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border bg-background/40">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">Diagnostics</span>
          <Badge variant="secondary" className="h-5 text-[10px]">
            {stepEntries.length} steps
          </Badge>
          {totalWarns > 0 && (
            <Badge className="h-5 bg-amber-500/10 text-amber-700 hover:bg-amber-500/10 dark:text-amber-400">
              {totalWarns} warning{totalWarns === 1 ? "" : "s"}
            </Badge>
          )}
          {totalErrors > 0 && (
            <Badge className="h-5 bg-destructive/10 text-destructive hover:bg-destructive/10">
              {totalErrors} error{totalErrors === 1 ? "" : "s"}
            </Badge>
          )}
        </div>
        <CollapsibleTrigger asChild>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs">
            {open ? <ChevronDown className="mr-1 h-3 w-3" /> : <ChevronRight className="mr-1 h-3 w-3" />}
            {open ? "Hide" : "Show"} details
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className="border-t px-4 py-3">
        <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          {stepEntries.map(([step, c]) => (
            <div key={step} className="rounded border bg-card/40 px-2 py-1.5">
              <div className="font-medium capitalize">{step.replace(/_/g, " ")}</div>
              <div className="mt-0.5 text-muted-foreground">
                {c.info} ok
                {c.warn ? ` · ${c.warn} warn` : ""}
                {c.error ? ` · ${c.error} err` : ""}
              </div>
            </div>
          ))}
        </div>
        {recentEvents.length > 0 ? (
          <div className="max-h-56 overflow-auto rounded border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className="px-2 py-1 text-left">Time</th>
                  <th className="px-2 py-1 text-left">File</th>
                  <th className="px-2 py-1 text-left">Step</th>
                  <th className="px-2 py-1 text-left">Message</th>
                </tr>
              </thead>
              <tbody>
                {recentEvents.map((e, i) => (
                  <tr key={i} className="border-t">
                    <td className="px-2 py-1 tabular-nums text-muted-foreground">
                      {new Date(e.ts).toLocaleTimeString()}
                    </td>
                    <td className="max-w-[160px] truncate px-2 py-1">{e.file}</td>
                    <td className="px-2 py-1 capitalize">{e.step.replace(/_/g, " ")}</td>
                    <td className={`px-2 py-1 ${e.level === "error" ? "text-destructive" : "text-amber-600 dark:text-amber-400"}`}>
                      {e.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No warnings or errors in the latest batch.</p>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}



function UploadReport({
  jobs,
  running,
  onRetry,
  onOverwrite,
  onClearFinished,
}: {
  jobs: Job[];
  running: boolean;
  onRetry: (id: string) => void;
  onOverwrite: (id: string) => void;
  onClearFinished: () => void;
}) {
  const done = jobs.filter((j) => j.status === "done").length;
  const dupes = jobs.filter((j) => j.status === "duplicate").length;
  const errs = jobs.filter((j) => j.status === "error").length;
  const interrupted = jobs.filter((j) => j.status === "interrupted").length;
  const active = jobs.length - done - dupes - errs - interrupted;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-base">Upload report</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {active > 0 && `${active} in progress · `}
            {done} imported · {dupes} duplicate · {errs} failed
            {interrupted > 0 && ` · ${interrupted} interrupted`}
            {" · saved to this browser"}
          </p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onClearFinished}
          disabled={running || done + dupes + errs + interrupted === 0}
        >
          Clear finished
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <BatchSummary jobs={jobs} />
        <DiagnosticsPanel jobs={jobs} />
        <div className="space-y-3">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} onRetry={onRetry} onOverwrite={onOverwrite} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function JobRow({
  job,
  onRetry,
  onOverwrite,
}: {
  job: Job;
  onRetry: (id: string) => void;
  onOverwrite: (id: string) => void;
}) {
  const isError = job.status === "error";
  const isDuplicate = job.status === "duplicate";
  const isInterrupted = job.status === "interrupted";
  const isDone = job.status === "done";
  const isRunning = ["reading", "uploading", "processing"].includes(job.status);
  const [detailsOpen, setDetailsOpen] = useState(isError);
  const hasRowErrors = (job.rowErrors?.length ?? 0) > 0;
  const hasLogs = (job.logs?.length ?? 0) > 0;
  const canExport = isError || isDuplicate || hasRowErrors || hasLogs;

  return (
    <div
      className={`rounded-lg border p-3 ${
        isError
          ? "border-destructive/30 bg-destructive/5"
          : isDuplicate
            ? "border-amber-500/30 bg-amber-500/5"
            : isInterrupted
              ? "border-slate-500/30 bg-slate-500/5"
              : "bg-card"
      }`}
    >
      <div className="flex items-start gap-3">
        <FileSpreadsheet className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium">{job.name}</span>
            <span className="text-xs text-muted-foreground">
              {formatBytes(job.size)}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <StatusPill status={job.status} />
              {canExport && <ExportErrorsMenu job={job} />}
              {isDuplicate && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2"
                  onClick={() => onOverwrite(job.id)}
                >
                  <RotateCw className="mr-1 h-3 w-3" /> Overwrite
                </Button>
              )}
              {(isError || isDuplicate || isInterrupted) && (
                <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => onRetry(job.id)}>
                  <RotateCw className="mr-1 h-3 w-3" /> Retry
                </Button>
              )}
            </div>
          </div>

          <div className="mt-2">
            <Progress
              value={job.progress}
              className={`h-1.5 ${isRunning ? "animate-pulse" : ""} ${
                isError
                  ? "[&>div]:bg-destructive"
                  : isDuplicate
                    ? "[&>div]:bg-amber-500"
                    : isInterrupted
                      ? "[&>div]:bg-slate-500"
                      : isDone
                        ? "[&>div]:bg-emerald-500"
                        : ""
              }`}
            />
          </div>

          {isDone && (
            <p className="mt-2 text-xs text-muted-foreground">
              {job.overwritten ? "Overwrote previous upload · " : ""}
              Imported {job.insertedRows} of {job.totalRows ?? job.insertedRows} rows
              {job.duplicateRowsSkipped ? ` · ${job.duplicateRowsSkipped} duplicate rows skipped` : ""}
              {job.failedRows ? ` · ${job.failedRows} row${job.failedRows === 1 ? "" : "s"} failed validation` : ""}
              {job.tableName ? (
                <>
                  {" "}· stored in <code className="rounded bg-muted px-1">{job.tableName}</code>
                </>
              ) : null}
            </p>
          )}

          {isDuplicate && (
            <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
              {job.duplicateReason === "name" ? (
                <>
                  A file named <span className="font-medium">{job.name}</span> is already imported with different contents
                  {typeof job.existingRowCount === "number" ? <> ({job.existingRowCount} rows)</> : null}.
                  Rename the file to keep both, or click <span className="font-medium">Overwrite</span> to replace it.
                </>
              ) : (
                <>
                  Already imported — this file's contents are identical to
                  {job.existingFileName ? (
                    <> <span className="font-medium">"{job.existingFileName}"</span></>
                  ) : (
                    <> a previously uploaded file</>
                  )}
                  {typeof job.existingRowCount === "number" ? <> ({job.existingRowCount} rows)</> : null}
                  . Skipped automatically — click <span className="font-medium">Overwrite</span> to re-import.
                </>
              )}
            </p>
          )}

          {isError && job.invalidReason && (
            <p className="mt-2 text-xs text-destructive">
              {job.invalidReason === "empty"
                ? "This CSV is empty — it has no header row and no data rows."
                : job.invalidReason === "header_only"
                  ? "This CSV has a header row but no data rows. Add at least one data row and try again."
                  : "The first row of this CSV is blank, so no column headers could be detected."}
            </p>
          )}

          {isInterrupted && (
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
              This upload was interrupted by a page refresh. Click Retry to re-select and continue.
            </p>
          )}

          {hasRowErrors && !isError && (
            <p className="mt-2 text-xs text-muted-foreground">
              {job.rowErrors!.length} row{job.rowErrors!.length === 1 ? " was" : "s were"} skipped
              because of validation errors — download the report for details.
            </p>
          )}

          {isError && <ErrorPanel job={job} open={detailsOpen} onOpenChange={setDetailsOpen} />}
        </div>
      </div>
    </div>
  );
}

function ExportErrorsMenu({ job }: { job: Job }) {
  const download = (format: "csv" | "json") => {
    const entries: (RowError & { file: string; plainEnglish: string })[] = [];
    if (job.errorMessage) {
      entries.push({
        file: job.name,
        rowNumber: 0,
        reason: job.errorMessage,
        plainEnglish: hintFor(job.errorMessage) ?? job.errorMessage,
      });
    }
    if (job.status === "duplicate") {
      const msg =
        job.duplicateReason === "name"
          ? `Filename already exists (${job.name}). Rename the file to import as a new dataset.`
          : `File contents identical to previously uploaded file${job.existingFileName ? ` (${job.existingFileName})` : ""}.`;
      entries.push({ file: job.name, rowNumber: 0, reason: "duplicate_file", plainEnglish: msg });
    }
    for (const re of job.rowErrors ?? []) {
      entries.push({
        file: job.name,
        rowNumber: re.rowNumber,
        column: re.column,
        value: re.value,
        reason: re.reason,
        plainEnglish: hintForRow(re) ?? re.reason,
      });
    }

    let blob: Blob;
    let filename: string;
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const safeName = job.name.replace(/\.csv$/i, "").replace(/[^a-z0-9_-]+/gi, "_");
    if (format === "json") {
      blob = new Blob([JSON.stringify({ file: job.name, generatedAt: new Date().toISOString(), entries }, null, 2)], {
        type: "application/json",
      });
      filename = `errors-${safeName}-${ts}.json`;
    } else {
      const header = ["file", "row_number", "column", "value", "reason", "plain_english"];
      const escape = (v: unknown) => {
        const s = v === undefined || v === null ? "" : String(v);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const lines = [header.join(",")].concat(
        entries.map((e) =>
          [e.file, e.rowNumber || "", e.column ?? "", e.value ?? "", e.reason, e.plainEnglish].map(escape).join(","),
        ),
      );
      blob = new Blob([lines.join("\n")], { type: "text/csv" });
      filename = `errors-${safeName}-${ts}.csv`;
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${filename}`);
  };

  const downloadLogs = () => {
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const safeName = job.name.replace(/\.csv$/i, "").replace(/[^a-z0-9_-]+/gi, "_");
    const payload = {
      file: job.name,
      status: job.status,
      tableName: job.tableName,
      generatedAt: new Date().toISOString(),
      logs: job.logs ?? [],
      rowErrors: job.rowErrors ?? [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `logs-${safeName}-${ts}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success("Logs downloaded");
  };

  const hasErrorContent = !!job.errorMessage || job.status === "duplicate" || (job.rowErrors?.length ?? 0) > 0;
  const hasLogs = (job.logs?.length ?? 0) > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="ghost" className="h-7 px-2">
          <Download className="mr-1 h-3 w-3" /> Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {hasErrorContent && (
          <>
            <DropdownMenuItem onClick={() => download("csv")}>Errors as CSV</DropdownMenuItem>
            <DropdownMenuItem onClick={() => download("json")}>Errors as JSON</DropdownMenuItem>
          </>
        )}
        {hasLogs && (
          <DropdownMenuItem onClick={downloadLogs}>Processing logs (JSON)</DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}


function ErrorPanel({
  job,
  open,
  onOpenChange,
}: {
  job: Job;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const details = job.errorDetails ?? job.errorMessage ?? "Unknown error";
  const hint = hintFor(details);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        `File: ${job.name}\nError: ${job.errorMessage ?? ""}\n${job.errorStack ?? ""}`,
      );
      toast.success("Error details copied");
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };

  return (
    <div className="mt-2 rounded-md border border-destructive/30 bg-background/60 p-3">
      <div className="flex items-start gap-2">
        <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-destructive">
            {job.errorMessage || "Import failed"}
          </p>
          {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}

          <Collapsible open={open} onOpenChange={onOpenChange} className="mt-2">
            <div className="flex items-center gap-2">
              <CollapsibleTrigger asChild>
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs">
                  {open ? <ChevronDown className="mr-1 h-3 w-3" /> : <ChevronRight className="mr-1 h-3 w-3" />}
                  {open ? "Hide" : "Show"} technical details
                </Button>
              </CollapsibleTrigger>
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={copy}>
                <Copy className="mr-1 h-3 w-3" /> Copy
              </Button>
            </div>
            <CollapsibleContent className="mt-2">
              <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
                {details}
                {job.errorStack ? `\n\n${job.errorStack}` : ""}
              </pre>
              {(job.rowErrors?.length ?? 0) > 0 && (
                <div className="mt-2 max-h-40 overflow-auto rounded border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted">
                      <tr>
                        <th className="px-2 py-1 text-left">Row</th>
                        <th className="px-2 py-1 text-left">Column</th>
                        <th className="px-2 py-1 text-left">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {job.rowErrors!.slice(0, 50).map((re, i) => (
                        <tr key={i} className="border-t">
                          <td className="px-2 py-1 tabular-nums">{re.rowNumber}</td>
                          <td className="px-2 py-1">{re.column ?? "—"}</td>
                          <td className="px-2 py-1">{hintForRow(re) ?? re.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {job.rowErrors!.length > 50 && (
                    <p className="p-2 text-[11px] text-muted-foreground">
                      Showing first 50 of {job.rowErrors!.length} row errors — download the full report above.
                    </p>
                  )}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>
    </div>
  );
}

function hintFor(message: string): string | null {
  const m = message.toLowerCase();
  if (m.includes("header row")) return "The file must include a header row followed by at least one data row.";
  if (m.includes("no columns")) return "No usable column names were found in the first row of the CSV.";
  if (m.includes("invalid table name")) return "The server rejected the auto-generated table name. Try re-uploading the file.";
  if (m.includes("could not create table")) return "The database refused to create a table for this file. Check that column names in the header row are valid.";
  if (m.includes("insert failed")) return "Some rows could not be inserted. The most common cause is inconsistent numbers of columns across rows.";
  if (m.includes("could not register file")) return "The file was processed but its registry entry could not be written. Try again.";
  if (m.includes("network") || m.includes("fetch")) return "A network error interrupted the upload. Check your connection and retry.";
  return null;
}

function hintForRow(re: RowError): string | null {
  const r = re.reason.toLowerCase();
  if (r.includes("whole number")) return `Row ${re.rowNumber}: column "${re.column}" expected a whole number but got "${re.value}".`;
  if (r.includes("not a number")) return `Row ${re.rowNumber}: column "${re.column}" expected a number but got "${re.value}".`;
  if (r.includes("true/false")) return `Row ${re.rowNumber}: column "${re.column}" expected true/false but got "${re.value}".`;
  if (r.includes("date")) return `Row ${re.rowNumber}: column "${re.column}" expected a valid date but got "${re.value}".`;
  if (r.includes("timestamp")) return `Row ${re.rowNumber}: column "${re.column}" expected a valid timestamp but got "${re.value}".`;
  return `Row ${re.rowNumber}${re.column ? ` (${re.column})` : ""}: ${re.reason}`;
}

function PreviewDialog({
  pending,
  index,
  onPrev,
  onNext,
  onConfirm,
  onCancel,
}: {
  pending: PendingPreview[];
  index: number;
  onPrev: () => void;
  onNext: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const open = pending.length > 0;
  const current = pending[index];
  if (!current) return null;
  const { file, preview } = current;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-4xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4" /> Preview: {file.name}
          </DialogTitle>
          <DialogDescription>
            Confirm detected columns, inferred types, and a sample of rows before importing.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col space-y-3 overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">
              File {index + 1} of {pending.length}
            </Badge>
            <span>{formatBytes(file.size)}</span>
            <span>·</span>
            <span>{preview.headers.length} columns</span>
            <span>·</span>
            <span>
              {preview.truncated ? "~" : ""}
              {preview.totalRowsApprox} data rows{preview.truncated ? " (estimated)" : ""}
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-auto rounded border">

            <Table>
              <TableHeader className="sticky top-0 z-10 bg-background">
                <TableRow>
                  {preview.sanitizedHeaders.map((h, i) => (
                    <TableHead key={i} className="align-top">
                      <div className="flex flex-col gap-0.5 py-1">
                        <span className="text-xs font-semibold">{h}</span>
                        {preview.headers[i] !== h && (
                          <span className="text-[10px] text-muted-foreground">from "{preview.headers[i]}"</span>
                        )}
                        <span className="mt-1 inline-flex w-fit rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          {COLUMN_TYPE_LABEL[preview.inferredTypes[i]]}
                        </span>
                      </div>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.sampleRows.map((row, r) => (
                  <TableRow key={r}>
                    {preview.sanitizedHeaders.map((_, c) => (
                      <TableCell key={c} className="max-w-xs truncate text-xs">
                        {row[c] ?? ""}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
                {preview.sampleRows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={preview.sanitizedHeaders.length} className="text-center text-xs text-muted-foreground">
                      No data rows found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <p className="text-xs text-muted-foreground">
            Column names are sanitized for the database. Detected types come from the first {Math.min(preview.sampleRows.length, 200)} rows.
            Values that don't match a column's type will be reported as row errors instead of being imported.
          </p>
        </div>

        <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onPrev} disabled={index === 0}>
              Previous
            </Button>
            <Button variant="outline" size="sm" onClick={onNext} disabled={index >= pending.length - 1}>
              Next
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button onClick={onConfirm}>
              Confirm & import {pending.length > 1 ? `all ${pending.length}` : ""}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FilesList({ files }: { files: CsvFileSummary[] }) {
  const [preview, setPreview] = useState<CsvFileSummary | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileSpreadsheet className="h-4 w-4" />
          Migrated files
        </CardTitle>
      </CardHeader>
      <CardContent>
        {files.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No files yet — upload a CSV above to get started.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Table</TableHead>
                  <TableHead className="text-right">Columns</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {files.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-medium">{f.file_name}</TableCell>
                    <TableCell>
                      <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{f.table_name}</code>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{f.column_names.length}</TableCell>
                    <TableCell className="text-right tabular-nums">{f.row_count}</TableCell>
                    <TableCell className="text-muted-foreground">
                      <time dateTime={f.created_at} suppressHydrationWarning>
                        {new Date(f.created_at).toISOString().replace("T", " ").slice(0, 19) + " UTC"}
                      </time>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => setPreview(f)}>
                        <Eye className="mr-1 h-4 w-4" /> Preview
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-5xl flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="truncate">{preview?.file_name}</DialogTitle>
            <DialogDescription>
              First rows of the imported table.
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-auto">
            {preview ? <PreviewTable file={preview} /> : null}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function PreviewTable({ file }: { file: CsvFileSummary }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["csv-preview", file.table_name],
    queryFn: () => previewCsvTable(file.table_name, 50),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (error) return <p className="text-sm text-destructive">{(error as Error).message}</p>;

  const rows = data?.rows ?? [];
  return (
    <div className="overflow-auto rounded border">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            {file.column_names.map((c) => (
              <TableHead key={c}>{c}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {file.column_names.map((c) => (
                <TableCell key={c} className="max-w-xs truncate">
                  {String(row[c] ?? "")}
                </TableCell>
              ))}
            </TableRow>
          ))}
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={file.column_names.length} className="text-center text-muted-foreground">
                No rows.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <p className="p-2 text-xs text-muted-foreground">
        Showing up to 50 rows. Table has {file.row_count} row{file.row_count === 1 ? "" : "s"} total.
      </p>
    </div>
  );
}
