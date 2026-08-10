// ─── src/routes/audit.tsx ────────────────────────────────────────────────────
// Import audit log with filters, export, inline error view, bulk selection.
import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";
import { AUDIT_LOG } from "@/lib/audit-log";
import { useLocalStorageState } from "@/hooks/use-local-storage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CheckCircle2, AlertTriangle, XCircle, PauseCircle, ChevronDown, ChevronRight, Download, RotateCw, Search, FileText, CalendarRange } from "lucide-react";
import { toast } from "sonner";
import type { RowError, ColumnType, ProcessingLog } from "@/lib/csv.functions";
import type { ColumnMapping } from "@/lib/mapping-templates";
import { downloadErrorReport, downloadAuditReport, buildErrorRows, mappingSummary, type ExportFormat, type AuditReportRow } from "@/lib/export";

type JobStatus = "reading"|"uploading"|"processing"|"done"|"duplicate"|"error"|"interrupted"|"cancelled";
type Job = { id: string; batchId: string; name: string; size: number; status: JobStatus; progress: number; createdAt: number; insertedRows?: number; duplicateRowsSkipped?: number; failedRows?: number; totalRows?: number; tableName?: string; existingFileName?: string; duplicateReason?: "content"|"name"|"empty"; invalidReason?: "empty"|"header_only"|"no_columns"; existingRowCount?: number; overwritten?: boolean; replacedFileName?: string; errorMessage?: string; errorDetails?: string; errorStack?: string; rowErrors?: RowError[]; columns?: string[]; types?: ColumnType[]; logs?: ProcessingLog[]; headerMapping?: ColumnMapping[]; cancellationReason?: string; };

export const Route = createFileRoute("/audit")({ head: () => ({ meta: [{ title: "Audit log — CSV Migrator" }] }), component: AuditPage });

const STATUS_LABEL: Record<JobStatus,string> = { reading:"Reading", uploading:"Uploading", processing:"Processing", done:"Imported", duplicate:"Skipped duplicate", error:"Invalid structure", interrupted:"Interrupted", cancelled:"Cancelled" };
const FILTER_STATUSES = [ {value:"all",label:"All statuses"}, {value:"done",label:"Imported"}, {value:"overwritten",label:"Overwritten"}, {value:"duplicate",label:"Skipped duplicate"}, {value:"error",label:"Invalid structure"}, {value:"interrupted",label:"Interrupted"}, {value:"cancelled",label:"Cancelled"} ];

function statusIcon(s: JobStatus) {
  if (s==="done") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500"/>;
  if (s==="duplicate") return <AlertTriangle className="h-3.5 w-3.5 text-amber-500"/>;
  if (s==="error") return <XCircle className="h-3.5 w-3.5 text-destructive"/>;
  return <PauseCircle className="h-3.5 w-3.5 text-slate-400"/>;
}
function statusCls(s: JobStatus, ow?: boolean) {
  if (s==="done"&&ow) return "bg-blue-500/10 text-blue-700 dark:text-blue-400";
  if (s==="done") return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  if (s==="duplicate") return "bg-amber-500/10 text-amber-700 dark:text-amber-400";
  if (s==="error") return "bg-destructive/10 text-destructive";
  return "bg-slate-500/10 text-slate-600 dark:text-slate-400";
}
function fmtBytes(b: number) { if(b<1024) return `${b} B`; if(b<1048576) return `${(b/1024).toFixed(1)} KB`; return `${(b/1048576).toFixed(2)} MB`; }

function AuditPage() {
  const [jobs] = useLocalStorageState<Job[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [invalidRowsJob, setInvalidRowsJob] = useState<Job|null>(null);
  const [changelogOpen, setChangelogOpen] = useState(false);

  const terminalJobs = useMemo(() => jobs.filter(j=>!["reading","uploading","processing"].includes(j.status)), [jobs]);

  const filtered = useMemo(() => terminalJobs.filter(j => {
    if (search && !j.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter !== "all") {
      if (statusFilter === "overwritten") { if (j.status !== "done" || !j.overwritten) return false; }
      else if (j.status !== statusFilter) return false;
    }
    if (dateFrom && j.createdAt < new Date(dateFrom).getTime()) return false;
    if (dateTo && j.createdAt > new Date(dateTo).getTime() + 86400000) return false;
    return true;
  }), [terminalJobs, search, statusFilter, dateFrom, dateTo]);

  const allSelected = filtered.length > 0 && filtered.every(j => selectedIds.has(j.id));
  const toggleAll = useCallback(() => { setSelectedIds(prev => { const n=new Set(prev); allSelected ? filtered.forEach(j=>n.delete(j.id)) : filtered.forEach(j=>n.add(j.id)); return n; }); }, [allSelected, filtered]);
  const toggleOne = useCallback((id: string) => { setSelectedIds(prev => { const n=new Set(prev); n.has(id)?n.delete(id):n.add(id); return n; }); }, []);
  const selectedJobs = filtered.filter(j => selectedIds.has(j.id));

  const buildAuditRows = useCallback((js: Job[]): AuditReportRow[] => js.map(j => ({ file:j.name, status: j.status==="done"&&j.overwritten?"Overwritten":STATUS_LABEL[j.status], imported_at: new Date(j.createdAt).toISOString(), total_rows:j.totalRows??"", inserted_rows:j.insertedRows??"", duplicate_rows_skipped:j.duplicateRowsSkipped??"", failed_rows:j.failedRows??"", table_name:j.tableName??"", header_mapping:mappingSummary(j.headerMapping), cancellation_reason:j.cancellationReason??"" })), []);

  const handleDownloadAudit = (fmt: ExportFormat) => { downloadAuditReport(buildAuditRows(filtered), fmt); toast.success(`Audit report downloaded as ${fmt.toUpperCase()}`); };
  const handleBulkExport = (fmt: ExportFormat) => {
    const errJobs = selectedJobs.filter(j=>(j.rowErrors?.length??0)>0||j.errorMessage);
    if (!errJobs.length) { toast.info("No selected files have error rows to export."); return; }
    const rows = errJobs.flatMap(j=>buildErrorRows(j.name, j.rowErrors??[], j.errorMessage, j.headerMapping));
    downloadErrorReport(`${errJobs.length} files`, rows, fmt);
    toast.success(`Exported errors for ${errJobs.length} file(s)`);
  };
  const handleBulkRetry = () => {
    const retryable = selectedJobs.filter(j=>["error","duplicate","interrupted","cancelled"].includes(j.status));
    if (!retryable.length) { toast.info("No selected files are retryable."); return; }
    toast.info(`Re-select on the upload page: ${retryable.map(j=>j.name).join(", ")}`, {duration:8000});
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Import history</h1>
          <p className="mt-1 text-sm text-muted-foreground">{terminalJobs.length} import{terminalJobs.length!==1?"s":""} · saved locally</p>
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm"><Download className="mr-1.5 h-3.5 w-3.5"/>Audit report<ChevronDown className="ml-1.5 h-3 w-3 opacity-60"/></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={()=>handleDownloadAudit("csv")}>Download as CSV</DropdownMenuItem>
              <DropdownMenuItem onClick={()=>handleDownloadAudit("xlsx")}>Download as XLSX</DropdownMenuItem>
              <DropdownMenuItem onClick={()=>handleDownloadAudit("pdf")}>Print / save as PDF</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Link to="/" className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent">← Upload</Link>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground"/>
          <Input placeholder="Search filename…" value={search} onChange={e=>setSearch(e.target.value)} className="pl-8 h-9 text-sm"/>
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-[180px] text-sm"><SelectValue/></SelectTrigger>
          <SelectContent>{FILTER_STATUSES.map(s=><SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent>
        </Select>
        <CalendarRange className="self-center h-3.5 w-3.5 text-muted-foreground"/>
        <Input type="date" value={dateFrom} onChange={e=>setDateFrom(e.target.value)} className="h-9 w-[140px] text-sm" title="From"/>
        <span className="self-center text-xs text-muted-foreground">to</span>
        <Input type="date" value={dateTo} onChange={e=>setDateTo(e.target.value)} className="h-9 w-[140px] text-sm" title="To"/>
        {(search||statusFilter!=="all"||dateFrom||dateTo) && <Button variant="ghost" size="sm" onClick={()=>{setSearch("");setStatusFilter("all");setDateFrom("");setDateTo("");}}>Clear</Button>}
      </div>

      {/* Bulk actions */}
      {selectedIds.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          <span className="font-medium">{selectedIds.size} selected</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button size="sm" variant="outline" className="h-7"><Download className="mr-1 h-3 w-3"/>Export errors<ChevronDown className="ml-1 h-3 w-3 opacity-60"/></Button></DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onClick={()=>handleBulkExport("csv")}>As CSV</DropdownMenuItem>
                <DropdownMenuItem onClick={()=>handleBulkExport("xlsx")}>As XLSX</DropdownMenuItem>
                <DropdownMenuItem onClick={()=>handleBulkExport("pdf")}>Print / PDF</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button size="sm" variant="outline" className="h-7" onClick={handleBulkRetry}><RotateCw className="mr-1 h-3 w-3"/>Retry selected</Button>
          </div>
        </div>
      )}

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed py-16 text-center">
          <FileText className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40"/>
          <p className="text-sm text-muted-foreground">{terminalJobs.length===0?"No imports yet — upload CSV files to see them here.":"No imports match the current filters."}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8 px-3"><Checkbox checked={allSelected} onCheckedChange={toggleAll} aria-label="Select all"/></TableHead>
                <TableHead>File</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Rows</TableHead><TableHead>Date</TableHead><TableHead>Mapping</TableHead><TableHead/>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(job => (
                <TableRow key={job.id} className={selectedIds.has(job.id)?"bg-muted/30":undefined}>
                  <TableCell className="px-3"><Checkbox checked={selectedIds.has(job.id)} onCheckedChange={()=>toggleOne(job.id)} aria-label={`Select ${job.name}`}/></TableCell>
                  <TableCell><div className="flex flex-col"><span className="max-w-[220px] truncate text-sm font-medium">{job.name}</span><span className="text-xs text-muted-foreground">{fmtBytes(job.size)}</span></div></TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${statusCls(job.status,job.overwritten)}`}>{statusIcon(job.status)}{job.status==="done"&&job.overwritten?"Overwritten":STATUS_LABEL[job.status]}</span>
                    {job.cancellationReason && <p className="mt-0.5 text-[11px] text-muted-foreground">{job.cancellationReason}</p>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {job.totalRows!=null ? <div className="flex flex-col items-end gap-0.5"><span>{job.totalRows} total</span>{job.insertedRows!=null&&<span className="text-emerald-600 dark:text-emerald-400">{job.insertedRows} ok</span>}{(job.failedRows??0)>0&&<span className="text-destructive">{job.failedRows} failed</span>}</div> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground" suppressHydrationWarning>{new Date(job.createdAt).toISOString().replace("T"," ").slice(0,19)} UTC</TableCell>
                  <TableCell className="max-w-[160px] text-xs text-muted-foreground">{mappingSummary(job.headerMapping)||<span className="text-muted-foreground/40">—</span>}</TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {((job.rowErrors?.length??0)>0||job.errorMessage) && (
                        <>
                          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={()=>setInvalidRowsJob(job)}>View errors</Button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild><Button size="sm" variant="ghost" className="h-7 px-2"><Download className="h-3 w-3"/></Button></DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={()=>{const r=buildErrorRows(job.name,job.rowErrors??[],job.errorMessage,job.headerMapping);downloadErrorReport(job.name,r,"csv");toast.success("Downloaded");}}>As CSV</DropdownMenuItem>
                              <DropdownMenuItem onClick={()=>{const r=buildErrorRows(job.name,job.rowErrors??[],job.errorMessage,job.headerMapping);downloadErrorReport(job.name,r,"xlsx");toast.success("Downloaded");}}>As XLSX</DropdownMenuItem>
                              <DropdownMenuSeparator/>
                              <DropdownMenuItem onClick={()=>{const r=buildErrorRows(job.name,job.rowErrors??[],job.errorMessage,job.headerMapping);downloadErrorReport(job.name,r,"pdf");}}>Print / PDF</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </>
                      )}
                      {["error","duplicate","interrupted","cancelled"].includes(job.status) && (
                        <Button size="sm" variant="ghost" className="h-7 px-2" title="Retry" onClick={()=>toast.info(`Re-select "${job.name}" on the upload page to retry.`,{duration:6000})}><RotateCw className="h-3 w-3"/></Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Invalid rows modal */}
      <Dialog open={!!invalidRowsJob} onOpenChange={o=>!o&&setInvalidRowsJob(null)}>
        <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-4xl flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="truncate">Invalid rows — {invalidRowsJob?.name}</DialogTitle>
            <DialogDescription>{invalidRowsJob?.rowErrors?.length??0} row{(invalidRowsJob?.rowErrors?.length??0)!==1?"s":""} failed validation.{mappingSummary(invalidRowsJob?.headerMapping)&&` Header mapping: ${mappingSummary(invalidRowsJob?.headerMapping)}`}</DialogDescription>
          </DialogHeader>
          {invalidRowsJob?.errorMessage&&(invalidRowsJob?.rowErrors?.length??0)===0&&<div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{invalidRowsJob.errorMessage}</div>}
          {(invalidRowsJob?.rowErrors?.length??0)>0&&(
            <div className="min-h-0 flex-1 overflow-auto rounded border">
              <Table>
                <TableHeader className="sticky top-0 bg-background"><TableRow><TableHead className="w-16">Row #</TableHead><TableHead>Column</TableHead><TableHead>Value</TableHead><TableHead>Error</TableHead></TableRow></TableHeader>
                <TableBody>{invalidRowsJob!.rowErrors!.slice(0,200).map((re,i)=><TableRow key={i}><TableCell className="tabular-nums text-xs">{re.rowNumber}</TableCell><TableCell className="text-xs">{re.column??"—"}</TableCell><TableCell className="max-w-[180px] truncate text-xs font-mono">{re.value??"—"}</TableCell><TableCell className="text-xs text-destructive">{re.reason}</TableCell></TableRow>)}</TableBody>
              </Table>
              {(invalidRowsJob?.rowErrors?.length??0)>200&&<p className="p-2 text-[11px] text-muted-foreground">Showing 200 of {invalidRowsJob!.rowErrors!.length} rows — download for the full report.</p>}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2 border-t pt-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="outline" size="sm"><Download className="mr-1.5 h-3.5 w-3.5"/>Download report<ChevronDown className="ml-1.5 h-3 w-3 opacity-60"/></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {(["csv","xlsx"] as ExportFormat[]).map(fmt=><DropdownMenuItem key={fmt} onClick={()=>{if(!invalidRowsJob)return;const r=buildErrorRows(invalidRowsJob.name,invalidRowsJob.rowErrors??[],invalidRowsJob.errorMessage,invalidRowsJob.headerMapping);downloadErrorReport(invalidRowsJob.name,r,fmt);toast.success("Downloaded");}}>As {fmt.toUpperCase()}</DropdownMenuItem>)}
                <DropdownMenuSeparator/>
                <DropdownMenuItem onClick={()=>{if(!invalidRowsJob)return;const r=buildErrorRows(invalidRowsJob.name,invalidRowsJob.rowErrors??[],invalidRowsJob.errorMessage,invalidRowsJob.headerMapping);downloadErrorReport(invalidRowsJob.name,r,"pdf");}}>Print / save as PDF</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="ghost" size="sm" onClick={()=>setInvalidRowsJob(null)}>Close</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Changelog */}
      <div className="mt-10">
        <Collapsible open={changelogOpen} onOpenChange={setChangelogOpen}>
          <CollapsibleTrigger asChild>
            <button className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground">
              {changelogOpen?<ChevronDown className="h-4 w-4"/>:<ChevronRight className="h-4 w-4"/>}
              App changelog ({AUDIT_LOG.length} entries)
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-4">
            <ol className="space-y-4">
              {AUDIT_LOG.map((entry,i)=><li key={i} className="rounded-lg border bg-card p-4 shadow-sm"><div className="flex items-baseline justify-between gap-4"><h2 className="text-sm font-semibold">{entry.title}</h2><time className="shrink-0 text-xs text-muted-foreground">{entry.date}</time></div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{entry.changes.map((c,j)=><li key={j}>{c}</li>)}</ul></li>)}
            </ol>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
