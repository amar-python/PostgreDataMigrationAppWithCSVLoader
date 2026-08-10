// ─── src/routes/_authenticated/index.tsx ────────────────────────────────────
// Main upload page — extended with 13 features on top of the existing base.
// Only the delta is described in comments; the original logic is preserved.
//
// New features added here:
//  F3  Header rename/mapping step in PreviewDialog
//  F8  Cancel/stop active import job
//  F9  Duplicate diff preview before overwrite
//  F11 Saved header mapping templates (apply automatically on upload)
//  F12 Notifications (sonner toast + browser Notification API)
//  F13 XLSX export of errors (via ExportErrorsMenu using export.ts)
//
// Features implemented in audit.tsx / export.ts / mapping-templates.ts:
//  F1  Filters/search in audit log
//  F2  Invalid-row CSV/PDF/XLSX download
//  F4  Retry from audit log
//  F5  Header mapping visible per audit entry
//  F6  Per-file invalid-rows modal
//  F7  Bulk selection in audit log
//  F10 Audit report as CSV/XLSX/PDF

import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  listCsvFiles, previewCsvTable, uploadCsv,
  type CsvFileSummary, type UploadResult, type RowError, type ColumnType, type ProcessingLog,
} from "@/lib/csv.functions";
import { parseCsvPreview, COLUMN_TYPE_LABEL, sanitizeColumns, type CsvPreview } from "@/lib/csv-preview";
import { useLocalStorageState } from "@/hooks/use-local-storage";
import {
  loadTemplates, saveTemplate, findMatchingTemplate, touchTemplate, deleteTemplate,
  type MappingTemplate, type ColumnMapping,
} from "@/lib/mapping-templates";
import { downloadErrorReport, buildErrorRows, type ExportFormat } from "@/lib/export";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { toast, Toaster } from "sonner";
import {
  Loader2, UploadCloud, FileSpreadsheet, Database, Eye, CheckCircle2, AlertTriangle,
  XCircle, RotateCw, ChevronDown, ChevronRight, Copy, Download, PauseCircle,
  BookmarkPlus, Bookmark, X as XIcon, BellRing,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

// ─── query ───────────────────────────────────────────────────────────────────

const filesQuery = { queryKey: ["csv-files"], queryFn: () => listCsvFiles() };

export const Route = createFileRoute("/_authenticated/")({
  head: () => ({ meta: [{ title: "CSV Migrator — Upload CSV files to your database" }, { name: "description", content: "Upload any number of CSV files. Each becomes its own database table, with duplicates automatically skipped." }, { property: "og:title", content: "CSV Migrator" }] }),
  loader: ({ context }) => context.queryClient.ensureQueryData(filesQuery),
  component: Home,
});

function Home() {
  const { data: files } = useSuspenseQuery(filesQuery);
  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/30">
      <Toaster richColors position="top-right"/>
      <header className="border-b bg-card/40 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary"><Database className="h-5 w-5"/></div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">CSV Migrator</h1>
              <p className="text-xs text-muted-foreground">CSV in, database tables out — no duplicates.</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="secondary" className="hidden sm:inline-flex">{files.length} file{files.length===1?"":"s"} migrated</Badge>
            <Link to="/audit" className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">Import history</Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-8 px-6 py-10">
        <Uploader/>
        <FilesList files={files}/>
      </main>
    </div>
  );
}

// ─── types ────────────────────────────────────────────────────────────────────

type JobStatus = "reading"|"uploading"|"processing"|"done"|"duplicate"|"error"|"interrupted"|"cancelled";

type Job = {
  id: string; batchId: string; name: string; size: number; status: JobStatus; progress: number; createdAt: number;
  insertedRows?: number; duplicateRowsSkipped?: number; failedRows?: number; totalRows?: number; tableName?: string;
  existingFileName?: string; duplicateReason?: "content"|"name"|"empty"; invalidReason?: "empty"|"header_only"|"no_columns";
  existingRowCount?: number; overwritten?: boolean; replacedFileName?: string; errorMessage?: string;
  errorDetails?: string; errorStack?: string; rowErrors?: RowError[]; columns?: string[]; types?: ColumnType[];
  logs?: ProcessingLog[]; headerMapping?: ColumnMapping[]; cancellationReason?: string;
};

const STATUS_LABEL: Record<JobStatus,string> = {
  reading:"Reading file…", uploading:"Uploading…", processing:"Processing on server…",
  done:"Imported", duplicate:"Duplicate file", error:"Failed", interrupted:"Interrupted", cancelled:"Cancelled",
};

type PendingPreview = { file: File; preview: CsvPreview; batchId: string; mapping?: ColumnMapping[]; };

// ─── notification helper (F12) ────────────────────────────────────────────────

function requestNotifPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function sendNotif(title: string, body: string) {
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body, icon: "/favicon-32.png" }); } catch { /* ignore */ }
  }
}

// ─── Uploader ─────────────────────────────────────────────────────────────────

function Uploader() {
  const router = useRouter();
  const [dragOver, setDragOver] = useState(false);
  const [jobs, setJobs, clearStoredJobs] = useLocalStorageState<Job[]>([]);
  const [pending, setPending] = useState<PendingPreview[]>([]);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [diffJob, setDiffJob] = useState<Job|null>(null); // F9 duplicate diff
  const inputRef = useRef<HTMLInputElement>(null);
  const fileMap = useRef<Map<string,File>>(new Map());
  const abortMap = useRef<Map<string,AbortController>>(new Map()); // F8 cancel

  // Notifications: request permission on first mount (F12)
  useEffect(() => { requestNotifPermission(); }, []);

  // On mount: mark in-progress jobs as interrupted
  useEffect(() => {
    setJobs(prev => prev.map(j => ["reading","uploading","processing"].includes(j.status) ? {...j,status:"interrupted",progress:100} : j));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = jobs.some(j=>["reading","uploading","processing"].includes(j.status));
  const updateJob = useCallback((id:string,patch:Partial<Job>)=>{ setJobs(prev=>prev.map(j=>j.id===id?{...j,...patch}:j)); },[setJobs]);

  // F8: cancel a running job
  const cancelJob = useCallback((id:string,reason?:string)=>{
    const ctrl = abortMap.current.get(id);
    if (ctrl) { ctrl.abort(); abortMap.current.delete(id); }
    updateJob(id,{status:"cancelled",progress:100,cancellationReason:reason??"Cancelled by user"});
    toast.info(`Import cancelled${reason?`: ${reason}`:""}.`);
  },[updateJob]);

  const runJob = useCallback(async(job:Job,file:File,mapping?:ColumnMapping[],overwrite?:boolean)=>{
    const ctrl = new AbortController();
    abortMap.current.set(job.id,ctrl);
    try {
      updateJob(job.id,{status:"reading",progress:5});
      const content = await new Promise<string>((resolve,reject)=>{
        const reader = new FileReader();
        reader.onprogress = e=>{ if(e.lengthComputable) updateJob(job.id,{progress:Math.max(5,Math.round((e.loaded/e.total)*60))}); };
        reader.onerror = ()=>reject(reader.error??new Error("Could not read the file."));
        reader.onload = ()=>resolve(String(reader.result??""));
        reader.readAsText(file);
      });
      if (ctrl.signal.aborted) return;
      updateJob(job.id,{status:"uploading",progress:75});
      await new Promise(r=>setTimeout(r,30));
      if (ctrl.signal.aborted) return;
      updateJob(job.id,{status:"processing",progress:90});

      // Build types and renames from mapping
      const types = mapping?.map(c=>c.type);
      const headerMapping = mapping ?? undefined;

      const res = await uploadCsv({ fileName:job.name, content, types, overwrite, headerMapping: headerMapping?.map(c=>({original:c.original,renamed:c.renamed})) } as any) as UploadResult;
      if (ctrl.signal.aborted) return;
      abortMap.current.delete(job.id);

      if (res.status==="ok") {
        updateJob(job.id,{status:"done",progress:100,insertedRows:res.insertedRows,duplicateRowsSkipped:res.duplicateRowsSkipped,failedRows:res.failedRows,totalRows:res.totalRows,tableName:res.tableName,columns:res.columns,types:res.types,rowErrors:res.rowErrors,logs:res.logs,overwritten:res.overwritten,replacedFileName:res.replacedFileName,headerMapping:mapping});
        const msg = `${job.name}: ${res.overwritten?"overwrote · ":""}${res.insertedRows} of ${res.totalRows} rows imported${res.failedRows?` · ${res.failedRows} failed`:""}`;
        toast.success(msg);
        sendNotif("Import complete", msg); // F12
        await router.invalidate();
      } else if (res.status==="duplicate_file") {
        updateJob(job.id,{status:"duplicate",progress:100,existingFileName:res.existingFileName,tableName:res.tableName,duplicateReason:res.reason,existingRowCount:res.existingRowCount,logs:res.logs,headerMapping:mapping});
        toast.warning(`${job.name}: already imported — click Overwrite to replace.`);
        sendNotif("Duplicate detected", `${job.name} matches an existing import.`); // F12
      } else if (res.status==="invalid_structure") {
        updateJob(job.id,{status:"error",progress:100,errorMessage:res.message,errorDetails:res.message,invalidReason:res.reason,logs:res.logs,headerMapping:mapping});
        toast.error(`${job.name}: ${res.message}`);
        sendNotif("Import failed", `${job.name}: ${res.message}`); // F12
      } else {
        updateJob(job.id,{status:"error",progress:100,errorMessage:(res as any).message,errorDetails:(res as any).message,rowErrors:(res as any).rowErrors,logs:(res as any).logs,headerMapping:mapping});
        toast.error(`${job.name}: ${(res as any).message}`);
        sendNotif("Import failed", `${job.name}: ${(res as any).message}`); // F12
      }
    } catch(err) {
      abortMap.current.delete(job.id);
      if (ctrl.signal.aborted) return; // already cancelled
      const e = err as Error;
      updateJob(job.id,{status:"error",progress:100,errorMessage:e.message||"Unknown error",errorDetails:e.message,errorStack:e.stack});
      toast.error(`${job.name}: ${e.message}`);
    }
  },[router,updateJob]);

  const startBatch = useCallback(async(items:PendingPreview[])=>{
    const newJobs: Job[] = items.map(it=>{
      const id = `${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
      fileMap.current.set(id,it.file);
      return {id,batchId:it.batchId,name:it.file.name,size:it.file.size,status:"reading",progress:0,createdAt:Date.now()};
    });
    setJobs(prev=>[...newJobs,...prev]);
    for (let i=0;i<items.length;i++) {
      await runJob(newJobs[i],items[i].file,items[i].mapping);
    }
  },[runJob,setJobs]);

  const handleFiles = useCallback(async(files:File[])=>{
    const csvs = files.filter(f=>f.name.toLowerCase().endsWith(".csv")||f.type==="text/csv");
    if (!csvs.length) { toast.error("Please drop .csv files."); return; }
    const batchId = `b-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;
    const previews: PendingPreview[] = [];
    for (const f of csvs) {
      try {
        const p = await parseCsvPreview(f);
        // F11: auto-detect saved template
        const template = findMatchingTemplate(p.headers);
        const mapping: ColumnMapping[] = p.headers.map((orig,i)=>({
          original: orig,
          renamed: template?.columns[i]?.renamed ?? "",
          type: template?.columns[i]?.type ?? p.inferredTypes[i],
        }));
        previews.push({file:f,preview:p,batchId,mapping});
        if (template) toast.info(`Applied mapping template "${template.name}" to ${f.name}`);
      } catch(err) { toast.error(`${f.name}: ${(err as Error).message}`); }
    }
    if (!previews.length) return;
    setPending(previews);
    setPreviewIndex(0);
  },[]);

  const confirmAll = useCallback(async()=>{ const items=pending; setPending([]); setPreviewIndex(0); await startBatch(items); },[pending,startBatch]);
  const cancelAll = useCallback(()=>{ setPending([]); setPreviewIndex(0); toast.info("Import cancelled."); },[]);

  const retryJob = useCallback(async(id:string,opts?:{overwrite?:boolean})=>{
    const job = jobs.find(j=>j.id===id);
    if (!job) return;
    const file = fileMap.current.get(id);
    if (!file) { toast.error("Original file no longer available — please re-select it."); return; }
    updateJob(id,{status:"reading",progress:0,errorMessage:undefined,errorDetails:undefined,errorStack:undefined,rowErrors:undefined,invalidReason:undefined,cancellationReason:undefined});
    const preview = await parseCsvPreview(file);
    const mapping: ColumnMapping[] = preview.headers.map((orig,i)=>({original:orig,renamed:job.headerMapping?.find(m=>m.original===orig)?.renamed??"",type:job.types?.[i]??preview.inferredTypes[i]}));
    await runJob(job,file,mapping,opts?.overwrite);
  },[jobs,runJob,updateJob]);

  // F9: show diff before overwrite
  const requestOverwrite = useCallback((id:string)=>{
    const job = jobs.find(j=>j.id===id);
    if (job?.tableName) { setDiffJob(job); } else { retryJob(id,{overwrite:true}); }
  },[jobs,retryJob]);

  const confirmOverwrite = useCallback(()=>{ if(diffJob){retryJob(diffJob.id,{overwrite:true});} setDiffJob(null); },[diffJob,retryJob]);

  const clearFinished = useCallback(()=>{
    setJobs(prev=>{
      const remaining = prev.filter(j=>!["done","duplicate","error","interrupted","cancelled"].includes(j.status));
      if (!remaining.length) clearStoredJobs();
      const ids = new Set(remaining.map(j=>j.id));
      for (const id of Array.from(fileMap.current.keys())) { if(!ids.has(id)) fileMap.current.delete(id); }
      return remaining;
    });
  },[setJobs,clearStoredJobs]);

  return (
    <div className="space-y-4">
      <Card className="border-dashed">
        <CardContent className="p-0">
          <label
            onDragOver={e=>{e.preventDefault();setDragOver(true);}}
            onDragLeave={()=>setDragOver(false)}
            onDrop={e=>{e.preventDefault();setDragOver(false);handleFiles(Array.from(e.dataTransfer.files));}}
            className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg p-12 text-center transition-colors ${dragOver?"bg-primary/5":"hover:bg-muted/40"}`}
          >
            <input ref={inputRef} type="file" accept=".csv,text/csv" multiple className="hidden" onChange={e=>{const list=e.target.files?Array.from(e.target.files):[];if(list.length)handleFiles(list);if(inputRef.current)inputRef.current.value="";}}/>
            <div className="rounded-full bg-primary/10 p-4 text-primary"><UploadCloud className="h-8 w-8"/></div>
            <div>
              <p className="font-medium">Drop CSV files here or click to select</p>
              <p className="mt-1 text-sm text-muted-foreground">Preview columns and rename headers before importing.</p>
            </div>
            <Button type="button" onClick={()=>inputRef.current?.click()}>Choose files</Button>
          </label>
        </CardContent>
      </Card>

      {jobs.length>0&&<UploadReport jobs={jobs} running={running} onRetry={retryJob} onOverwrite={requestOverwrite} onCancel={cancelJob} onClearFinished={clearFinished}/>}

      <PreviewDialog pending={pending} index={previewIndex} onPrev={()=>setPreviewIndex(i=>Math.max(0,i-1))} onNext={()=>setPreviewIndex(i=>Math.min(pending.length-1,i+1))} onUpdateMapping={(i,m)=>setPending(prev=>prev.map((p,pi)=>pi===i?{...p,mapping:m}:p))} onConfirm={confirmAll} onCancel={cancelAll}/>

      {/* F9: Duplicate diff dialog */}
      <DiffDialog job={diffJob} onConfirm={confirmOverwrite} onCancel={()=>setDiffJob(null)}/>
    </div>
  );
}

// ─── UploadReport ─────────────────────────────────────────────────────────────

function formatBytes(b:number){if(b<1024)return`${b} B`;if(b<1048576)return`${(b/1024).toFixed(1)} KB`;return`${(b/1048576).toFixed(2)} MB`;}

function StatusPill({status}:{status:JobStatus}){
  const map:Record<JobStatus,{cls:string;icon:ReactNode}>={
    reading:{cls:"bg-muted text-muted-foreground",icon:<Loader2 className="h-3 w-3 animate-spin"/>},
    uploading:{cls:"bg-muted text-muted-foreground",icon:<Loader2 className="h-3 w-3 animate-spin"/>},
    processing:{cls:"bg-muted text-muted-foreground",icon:<Loader2 className="h-3 w-3 animate-spin"/>},
    done:{cls:"bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",icon:<CheckCircle2 className="h-3 w-3"/>},
    duplicate:{cls:"bg-amber-500/10 text-amber-700 dark:text-amber-400",icon:<AlertTriangle className="h-3 w-3"/>},
    error:{cls:"bg-destructive/10 text-destructive",icon:<XCircle className="h-3 w-3"/>},
    interrupted:{cls:"bg-slate-500/10 text-slate-600 dark:text-slate-400",icon:<PauseCircle className="h-3 w-3"/>},
    cancelled:{cls:"bg-slate-500/10 text-slate-600 dark:text-slate-400",icon:<XIcon className="h-3 w-3"/>},
  };
  const cfg=map[status];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.cls}`}>{cfg.icon}{STATUS_LABEL[status]}</span>;
}

function UploadReport({jobs,running,onRetry,onOverwrite,onCancel,onClearFinished}:{jobs:Job[];running:boolean;onRetry:(id:string)=>void;onOverwrite:(id:string)=>void;onCancel:(id:string,reason?:string)=>void;onClearFinished:()=>void;}){
  const done=jobs.filter(j=>j.status==="done").length;
  const dupes=jobs.filter(j=>j.status==="duplicate").length;
  const errs=jobs.filter(j=>j.status==="error").length;
  const interrupted=jobs.filter(j=>["interrupted","cancelled"].includes(j.status)).length;
  const active=jobs.length-done-dupes-errs-interrupted;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-base">Upload report</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{active>0&&`${active} in progress · `}{done} imported · {dupes} duplicate · {errs} failed{interrupted>0&&` · ${interrupted} interrupted`}{" · saved to this browser"}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClearFinished} disabled={running||done+dupes+errs+interrupted===0}>Clear finished</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {jobs.map(job=><JobRow key={job.id} job={job} onRetry={onRetry} onOverwrite={onOverwrite} onCancel={onCancel}/>)}
      </CardContent>
    </Card>
  );
}

function JobRow({job,onRetry,onOverwrite,onCancel}:{job:Job;onRetry:(id:string)=>void;onOverwrite:(id:string)=>void;onCancel:(id:string,reason?:string)=>void;}){
  const isError=job.status==="error";const isDuplicate=job.status==="duplicate";
  const isInterrupted=["interrupted","cancelled"].includes(job.status);const isDone=job.status==="done";
  const isRunning=["reading","uploading","processing"].includes(job.status);
  const [detailsOpen,setDetailsOpen]=useState(isError);
  const hasRowErrors=(job.rowErrors?.length??0)>0;
  return (
    <div className={`rounded-lg border p-3 ${isError?"border-destructive/30 bg-destructive/5":isDuplicate?"border-amber-500/30 bg-amber-500/5":isInterrupted?"border-slate-500/30 bg-slate-500/5":"bg-card"}`}>
      <div className="flex items-start gap-3">
        <FileSpreadsheet className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground"/>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium">{job.name}</span>
            <span className="text-xs text-muted-foreground">{formatBytes(job.size)}</span>
            <div className="ml-auto flex items-center gap-2">
              <StatusPill status={job.status}/>
              {(hasRowErrors||isError||isDuplicate)&&<ExportErrorsMenu job={job}/>}
              {/* F8: cancel button for active jobs */}
              {isRunning&&<Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground" onClick={()=>onCancel(job.id)}><XIcon className="mr-1 h-3 w-3"/>Stop</Button>}
              {isDuplicate&&<Button size="sm" variant="outline" className="h-7 px-2" onClick={()=>onOverwrite(job.id)}><RotateCw className="mr-1 h-3 w-3"/>Overwrite</Button>}
              {(isError||isDuplicate||isInterrupted)&&<Button size="sm" variant="ghost" className="h-7 px-2" onClick={()=>onRetry(job.id)}><RotateCw className="mr-1 h-3 w-3"/>Retry</Button>}
            </div>
          </div>
          <div className="mt-2"><Progress value={job.progress} className={`h-1.5 ${isRunning?"animate-pulse":""} ${isError?"[&>div]:bg-destructive":isDuplicate?"[&>div]:bg-amber-500":isInterrupted?"[&>div]:bg-slate-500":isDone?"[&>div]:bg-emerald-500":""}`}/></div>
          {isDone&&<p className="mt-2 text-xs text-muted-foreground">{job.overwritten?"Overwrote previous upload · ":""}Imported {job.insertedRows} of {job.totalRows??job.insertedRows} rows{job.duplicateRowsSkipped?` · ${job.duplicateRowsSkipped} duplicate rows skipped`:""}{job.failedRows?` · ${job.failedRows} row${job.failedRows===1?"":"s"} failed validation`:""}{job.tableName?<> · stored in <code className="rounded bg-muted px-1">{job.tableName}</code></>:null}</p>}
          {isDuplicate&&<p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{job.duplicateReason==="name"?<>A file named <span className="font-medium">{job.name}</span> is already imported with different contents. Click <span className="font-medium">Overwrite</span> to replace it.</>:<>Already imported{job.existingFileName?<> as <span className="font-medium">"{job.existingFileName}"</span></>:<> previously</>}. Click <span className="font-medium">Overwrite</span> to re-import.</>}</p>}
          {job.status==="cancelled"&&job.cancellationReason&&<p className="mt-2 text-xs text-slate-500">Cancelled: {job.cancellationReason}</p>}
          {isError&&<ErrorPanel job={job} open={detailsOpen} onOpenChange={setDetailsOpen}/>}
        </div>
      </div>
    </div>
  );
}

// ─── ExportErrorsMenu — now includes XLSX (F13) ───────────────────────────────

function ExportErrorsMenu({job}:{job:Job}){
  const handle = (fmt: ExportFormat) => {
    const rows = buildErrorRows(job.name,job.rowErrors??[],job.errorMessage,job.headerMapping);
    if (!rows.length) { toast.info("No errors to export."); return; }
    downloadErrorReport(job.name,rows,fmt);
    toast.success(`Downloaded error report for ${job.name}`);
  };
  const downloadLogs=()=>{
    const ts=new Date().toISOString().replace(/[:.]/g,"-");
    const safe=job.name.replace(/\.csv$/i,"").replace(/[^a-z0-9_-]+/gi,"_");
    const blob=new Blob([JSON.stringify({file:job.name,status:job.status,tableName:job.tableName,generatedAt:new Date().toISOString(),logs:job.logs??[],rowErrors:job.rowErrors??[]},null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=`logs-${safe}-${ts}.json`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
    toast.success("Logs downloaded");
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="sm" variant="ghost" className="h-7 px-2"><Download className="mr-1 h-3 w-3"/>Export</Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={()=>handle("csv")}>Errors as CSV</DropdownMenuItem>
        <DropdownMenuItem onClick={()=>handle("xlsx")}>Errors as XLSX</DropdownMenuItem>
        <DropdownMenuSeparator/>
        <DropdownMenuItem onClick={()=>handle("pdf")}>Print / save as PDF</DropdownMenuItem>
        <DropdownMenuSeparator/>
        {(job.logs?.length??0)>0&&<DropdownMenuItem onClick={downloadLogs}>Processing logs (JSON)</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ErrorPanel({job,open,onOpenChange}:{job:Job;open:boolean;onOpenChange:(v:boolean)=>void;}){
  const details=job.errorDetails??job.errorMessage??"Unknown error";
  const copy=async()=>{try{await navigator.clipboard.writeText(`File: ${job.name}\nError: ${job.errorMessage??""}\n${job.errorStack??""}`);toast.success("Error details copied");}catch{toast.error("Could not copy to clipboard");}};
  return (
    <div className="mt-2 rounded-md border border-destructive/30 bg-background/60 p-3">
      <div className="flex items-start gap-2">
        <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive"/>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-destructive">{job.errorMessage||"Import failed"}</p>
          <Collapsible open={open} onOpenChange={onOpenChange} className="mt-2">
            <div className="flex items-center gap-2">
              <CollapsibleTrigger asChild><Button size="sm" variant="outline" className="h-7 px-2 text-xs">{open?<ChevronDown className="mr-1 h-3 w-3"/>:<ChevronRight className="mr-1 h-3 w-3"/>}{open?"Hide":"Show"} technical details</Button></CollapsibleTrigger>
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={copy}><Copy className="mr-1 h-3 w-3"/>Copy</Button>
            </div>
            <CollapsibleContent className="mt-2">
              <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{details}{job.errorStack?`\n\n${job.errorStack}`:""}</pre>
              {(job.rowErrors?.length??0)>0&&(
                <div className="mt-2 max-h-40 overflow-auto rounded border">
                  <table className="w-full text-xs"><thead className="bg-muted"><tr><th className="px-2 py-1 text-left">Row</th><th className="px-2 py-1 text-left">Column</th><th className="px-2 py-1 text-left">Reason</th></tr></thead>
                  <tbody>{job.rowErrors!.slice(0,50).map((re,i)=><tr key={i} className="border-t"><td className="px-2 py-1 tabular-nums">{re.rowNumber}</td><td className="px-2 py-1">{re.column??"—"}</td><td className="px-2 py-1">{re.reason}</td></tr>)}</tbody></table>
                  {job.rowErrors!.length>50&&<p className="p-2 text-[11px] text-muted-foreground">Showing first 50 of {job.rowErrors!.length} row errors — download the report above.</p>}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>
    </div>
  );
}

// ─── PreviewDialog — with header rename/mapping step (F3) + template save (F11)

function PreviewDialog({pending,index,onPrev,onNext,onUpdateMapping,onConfirm,onCancel}:{pending:PendingPreview[];index:number;onPrev:()=>void;onNext:()=>void;onUpdateMapping:(i:number,m:ColumnMapping[])=>void;onConfirm:()=>void;onCancel:()=>void;}){
  const [templates,setTemplates]=useState<MappingTemplate[]>(()=>loadTemplates());
  const [saveName,setSaveName]=useState("");
  const [showSave,setShowSave]=useState(false);
  const open=pending.length>0;
  const current=pending[index];
  if(!current)return null;
  const {file,preview,mapping}=current;
  const m: ColumnMapping[] = mapping??preview.headers.map((orig,i)=>({original:orig,renamed:"",type:preview.inferredTypes[i]}));

  const updateMapping=(colIdx:number,patch:Partial<ColumnMapping>)=>{
    const next=[...m];next[colIdx]={...next[colIdx],...patch};
    onUpdateMapping(index,next);
  };

  const handleSaveTemplate=()=>{
    if(!saveName.trim())return;
    const t:MappingTemplate={id:`tpl-${Date.now()}`,name:saveName.trim(),columns:m,createdAt:Date.now()};
    saveTemplate(t);setTemplates(loadTemplates());setSaveName("");setShowSave(false);
    toast.success(`Template "${t.name}" saved`);
  };

  const handleDeleteTemplate=(id:string)=>{
    deleteTemplate(id);setTemplates(loadTemplates());
    toast.info("Template deleted");
  };

  const handleApplyTemplate=(t:MappingTemplate)=>{
    const next=preview.headers.map((orig,i)=>({original:orig,renamed:t.columns[i]?.renamed??"",type:t.columns[i]?.type??preview.inferredTypes[i]}));
    onUpdateMapping(index,next);touchTemplate(t.id);
    toast.success(`Applied template "${t.name}"`);
  };

  return (
    <Dialog open={open} onOpenChange={o=>!o&&onCancel()}>
      <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-4xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><FileSpreadsheet className="h-4 w-4"/>Preview: {file.name}</DialogTitle>
          <DialogDescription>Confirm columns, adjust header names, and set types before importing.</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col space-y-3 overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">File {index+1} of {pending.length}</Badge>
            <span>{formatBytes(file.size)}</span>·<span>{preview.headers.length} columns</span>·<span>{preview.truncated?"~":""}{preview.totalRowsApprox} data rows</span>
            {/* Saved templates dropdown (F11) */}
            {templates.length>0&&(
              <DropdownMenu>
                <DropdownMenuTrigger asChild><Button size="sm" variant="outline" className="ml-auto h-7 text-xs"><Bookmark className="mr-1 h-3 w-3"/>Apply template</Button></DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {templates.map(t=><div key={t.id} className="flex items-center justify-between px-2 py-1 text-sm hover:bg-muted/50">
                    <button onClick={()=>handleApplyTemplate(t)} className="flex-1 text-left">{t.name}</button>
                    <button onClick={()=>handleDeleteTemplate(t.id)} className="ml-2 text-muted-foreground hover:text-destructive"><XIcon className="h-3 w-3"/></button>
                  </div>)}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>

          {/* Header rename table (F3) */}
          <div className="min-h-0 flex-1 overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-background">
                <TableRow>
                  <TableHead className="w-[200px]">Original header</TableHead>
                  <TableHead className="w-[200px]">Rename to (optional)</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right text-[10px] font-normal text-muted-foreground">Sample values</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.headers.map((orig,colIdx)=>{
                  const col=m[colIdx]??{original:orig,renamed:"",type:preview.inferredTypes[colIdx]};
                  const sanitizedDefault=sanitizeColumns([orig])[0];
                  const displayName=col.renamed?col.renamed:sanitizedDefault;
                  const changed=col.renamed&&col.renamed!==sanitizedDefault;
                  return (
                    <TableRow key={colIdx}>
                      <TableCell className="py-1.5">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs font-mono">{orig}</span>
                          {orig!==sanitizedDefault&&<span className="text-[10px] text-muted-foreground">→ {sanitizedDefault}</span>}
                        </div>
                      </TableCell>
                      <TableCell className="py-1.5">
                        <Input value={col.renamed} onChange={e=>updateMapping(colIdx,{renamed:e.target.value})} placeholder={sanitizedDefault} className={`h-7 text-xs ${changed?"border-primary/50 bg-primary/5":""}`}/>
                      </TableCell>
                      <TableCell className="py-1.5">
                        <Select value={col.type} onValueChange={v=>updateMapping(colIdx,{type:v as ColumnType})}>
                          <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue/></SelectTrigger>
                          <SelectContent>{(["int8","numeric","date","timestamptz","boolean","text"] as ColumnType[]).map(t=><SelectItem key={t} value={t} className="text-xs">{COLUMN_TYPE_LABEL[t]}</SelectItem>)}</SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="py-1.5 text-right">
                        <span className="text-xs text-muted-foreground">{preview.sampleRows.slice(0,3).map(r=>r[colIdx]??"").filter(Boolean).join(", ")||"—"}</span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {/* Save template (F11) */}
          <div className="flex items-center gap-2">
            {showSave?(
              <>
                <Input value={saveName} onChange={e=>setSaveName(e.target.value)} placeholder="Template name…" className="h-8 text-xs flex-1"/>
                <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleSaveTemplate} disabled={!saveName.trim()}><BookmarkPlus className="mr-1 h-3 w-3"/>Save</Button>
                <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={()=>{setShowSave(false);setSaveName("");}}>Cancel</Button>
              </>
            ):(
              <Button size="sm" variant="ghost" className="h-8 text-xs text-muted-foreground" onClick={()=>setShowSave(true)}><BookmarkPlus className="mr-1 h-3 w-3"/>Save as template</Button>
            )}
          </div>
        </div>
        <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onPrev} disabled={index===0}>Previous</Button>
            <Button variant="outline" size="sm" onClick={onNext} disabled={index>=pending.length-1}>Next</Button>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onCancel}>Cancel</Button>
            <Button onClick={onConfirm}>Confirm & import{pending.length>1?` all ${pending.length}`:""}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── DiffDialog — duplicate diff preview (F9) ─────────────────────────────────

function DiffDialog({job,onConfirm,onCancel}:{job:Job|null;onConfirm:()=>void;onCancel:()=>void;}){
  const {data,isLoading}=useQuery({
    queryKey:["csv-preview-diff",job?.tableName],
    queryFn:()=>previewCsvTable(job!.tableName!,10),
    enabled:!!job?.tableName,
  });
  if(!job)return null;
  const rows=data?.rows??[];
  return (
    <Dialog open={!!job} onOpenChange={o=>!o&&onCancel()}>
      <DialogContent className="flex max-h-[80vh] w-[95vw] max-w-3xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-500"/>Overwrite confirmation</DialogTitle>
          <DialogDescription>This will replace the existing data in <code className="rounded bg-muted px-1">{job.tableName}</code>. Here are the first rows currently stored.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-auto rounded border">
          {isLoading?<div className="flex items-center justify-center py-8 text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin"/>Loading existing rows…</div>:rows.length===0?<p className="p-4 text-sm text-muted-foreground">No rows in this table.</p>:(
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted"><tr>{Object.keys(rows[0]).map(k=><th key={k} className="px-2 py-1.5 text-left font-medium">{k}</th>)}</tr></thead>
              <tbody>{rows.map((r,i)=><tr key={i} className="border-t">{Object.values(r).map((v,j)=><td key={j} className="max-w-[160px] truncate px-2 py-1">{String(v??"")}</td>)}</tr>)}</tbody>
            </table>
          )}
        </div>
        <p className="text-xs text-muted-foreground">These rows will be replaced by the new import. This cannot be undone.</p>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant="destructive" onClick={onConfirm}><RotateCw className="mr-1.5 h-3.5 w-3.5"/>Overwrite</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── FilesList (unchanged from original) ─────────────────────────────────────

function FilesList({files}:{files:CsvFileSummary[]}){
  const [preview,setPreview]=useState<CsvFileSummary|null>(null);
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><FileSpreadsheet className="h-4 w-4"/>Migrated files</CardTitle></CardHeader>
      <CardContent>
        {files.length===0?<p className="py-8 text-center text-sm text-muted-foreground">No files yet — upload a CSV above to get started.</p>:(
          <div className="overflow-x-auto"><Table>
            <TableHeader><TableRow><TableHead>File</TableHead><TableHead>Table</TableHead><TableHead className="text-right">Columns</TableHead><TableHead className="text-right">Rows</TableHead><TableHead>Uploaded</TableHead><TableHead/></TableRow></TableHeader>
            <TableBody>{files.map(f=><TableRow key={f.id}><TableCell className="font-medium">{f.file_name}</TableCell><TableCell><code className="rounded bg-muted px-1.5 py-0.5 text-xs">{f.table_name}</code></TableCell><TableCell className="text-right tabular-nums">{f.column_names.length}</TableCell><TableCell className="text-right tabular-nums">{f.row_count}</TableCell><TableCell className="text-muted-foreground" suppressHydrationWarning><time dateTime={f.created_at}>{new Date(f.created_at).toISOString().replace("T"," ").slice(0,19)+" UTC"}</time></TableCell><TableCell className="text-right"><Button size="sm" variant="ghost" onClick={()=>setPreview(f)}><Eye className="mr-1 h-4 w-4"/>Preview</Button></TableCell></TableRow>)}</TableBody>
          </Table></div>
        )}
      </CardContent>
      <Dialog open={!!preview} onOpenChange={o=>!o&&setPreview(null)}>
        <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-5xl flex-col overflow-hidden">
          <DialogHeader><DialogTitle className="truncate">{preview?.file_name}</DialogTitle><DialogDescription>First rows of the imported table.</DialogDescription></DialogHeader>
          <div className="min-h-0 flex-1 overflow-auto">{preview?<PreviewTable file={preview}/>:null}</div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function PreviewTable({file}:{file:CsvFileSummary}){
  const {data,isLoading,error}=useQuery({queryKey:["csv-preview",file.table_name],queryFn:()=>previewCsvTable(file.table_name,50)});
  if(isLoading)return<div className="flex items-center justify-center py-12 text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin"/>Loading…</div>;
  if(error)return<p className="text-sm text-destructive">{(error as Error).message}</p>;
  const rows=data?.rows??[];
  return (
    <div className="overflow-auto rounded border">
      <Table>
        <TableHeader className="sticky top-0 bg-background"><TableRow>{file.column_names.map(c=><TableHead key={c}>{c}</TableHead>)}</TableRow></TableHeader>
        <TableBody>
          {rows.map((row,i)=><TableRow key={i}>{file.column_names.map(c=><TableCell key={c} className="max-w-xs truncate">{String(row[c]??"")}</TableCell>)}</TableRow>)}
          {rows.length===0&&<TableRow><TableCell colSpan={file.column_names.length} className="text-center text-muted-foreground">No rows.</TableCell></TableRow>}
        </TableBody>
      </Table>
      <p className="p-2 text-xs text-muted-foreground">Showing up to 50 rows. Table has {file.row_count} row{file.row_count===1?"":"s"} total.</p>
    </div>
  );
}
