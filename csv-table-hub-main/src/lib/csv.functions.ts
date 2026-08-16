import { z } from "zod";

const columnTypeSchema = z.enum(["int8", "numeric", "date", "timestamptz", "boolean", "text"]);
export type ColumnType = z.infer<typeof columnTypeSchema>;

const rowErrorSchema = z.object({
  rowNumber: z.number(),
  column: z.string().optional(),
  value: z.string().optional(),
  reason: z.string(),
});
export type RowError = z.infer<typeof rowErrorSchema>;

const processingLogSchema = z.object({
  ts: z.number(),
  step: z.enum([
    "receive",
    "hash",
    "duplicate_check",
    "parse",
    "validate_columns",
    "create_table",
    "cast_rows",
    "insert",
    "register",
    "overwrite",
    "done",
    "error",
  ]),
  level: z.enum(["info", "warn", "error"]),
  message: z.string(),
  count: z.number().optional(),
  sql: z.string().optional(),
});
export type ProcessingLog = z.infer<typeof processingLogSchema>;

const uploadResultSchema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("ok"),
    fileId: z.string(),
    tableName: z.string(),
    totalRows: z.number(),
    insertedRows: z.number(),
    duplicateRowsSkipped: z.number(),
    failedRows: z.number(),
    columns: z.array(z.string()),
    types: z.array(columnTypeSchema),
    rowErrors: z.array(rowErrorSchema),
    logs: z.array(processingLogSchema),
    overwritten: z.boolean().optional(),
    // The backend always sends this key (dynamic_loader.py's replaced_file_name
    // starts as None and is JSON-serialised to null on every non-overwrite
    // upload — it's not merely omitted). .optional() alone only permits
    // undefined/absent, not null, so every first-time upload failed this
    // schema despite succeeding on the backend. Discovered via manual
    // browser verification of #24 (T&E mode UI) — the upload registered
    // server-side (visible in /api/csv/files) while the UI reported "Failed".
    replacedFileName: z.string().nullable().optional(),
  }),
  z.object({
    status: z.literal("duplicate_file"),
    reason: z.enum(["content", "name"]),
    existingFileName: z.string(),
    tableName: z.string(),
    existingRowCount: z.number().optional(),
    logs: z.array(processingLogSchema),
  }),
  z.object({
    status: z.literal("invalid_structure"),
    reason: z.enum(["empty", "header_only", "no_columns"]),
    message: z.string(),
    logs: z.array(processingLogSchema),
  }),
  z.object({
    status: z.literal("error"),
    message: z.string(),
    rowErrors: z.array(rowErrorSchema).optional(),
    logs: z.array(processingLogSchema),
  }),
]);
export type UploadResult = z.infer<typeof uploadResultSchema>;

const csvFileSummarySchema = z.object({
  id: z.string(),
  file_name: z.string(),
  table_name: z.string(),
  row_count: z.number(),
  column_names: z.array(z.string()),
  created_at: z.string(),
});
export type CsvFileSummary = z.infer<typeof csvFileSummarySchema>;

const csvFileSummaryListSchema = z.array(csvFileSummarySchema);

const previewRowValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
const previewRowsSchema = z.object({
  rows: z.array(z.record(previewRowValueSchema)),
});

const apiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const apiKey = import.meta.env.VITE_API_KEY ?? "";

async function apiFetch<T>(path: string, schema: z.ZodType<T>, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
      ...options?.headers,
    },
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const message = (payload as any)?.message || (payload as any)?.error || response.statusText;
    throw new Error(typeof message === "string" ? message : String(payload));
  }

  const result = schema.safeParse(payload);
  if (!result.success) {
    const issues = result.error.issues
      .map((issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`)
      .join("; ");
    throw new Error(`Unexpected response shape from ${path}: ${issues}`);
  }

  return result.data;
}

export async function uploadCsv(input: {
  fileName: string;
  content: string;
  types?: ColumnType[];
  overwrite?: boolean;
  mode?: "dynamic" | "te";
  targetTable?: string;
  headerMapping?: { original: string; renamed: string }[];
}): Promise<UploadResult> {
  return apiFetch("/api/csv/upload", uploadResultSchema, {
    method: "POST",
    body: JSON.stringify({
      fileName: input.fileName,
      content: input.content,
      types: input.types,
      overwrite: input.overwrite ?? false,
      mode: input.mode ?? "dynamic",
      targetTable: input.targetTable,
      headerMapping: input.headerMapping,
    }),
  });
}

export async function listCsvFiles(): Promise<CsvFileSummary[]> {
  return apiFetch("/api/csv/files", csvFileSummaryListSchema);
}

const csvPreviewResultSchema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("ok"),
    headers: z.array(z.string()),
    columns: z.array(z.string()),
    inferredTypes: z.array(columnTypeSchema),
    sampleRows: z.array(z.array(z.string())),
    totalRowsApprox: z.number(),
    teTableMatch: z.string().nullable().optional(),
  }),
  z.object({
    status: z.literal("invalid_structure"),
    reason: z.enum(["empty", "header_only", "no_columns"]),
  }),
]);
export type CsvPreviewResult = z.infer<typeof csvPreviewResultSchema>;

/** Server-side preview — used here only for its `teTableMatch` suggestion
 * (best-effort T&E table match); the header/type preview itself is done
 * client-side by parseCsvPreview() in csv-preview.ts. */
export async function previewCsv(fileName: string, content: string): Promise<CsvPreviewResult> {
  return apiFetch("/api/csv/preview", csvPreviewResultSchema, {
    method: "POST",
    body: JSON.stringify({ fileName, content }),
  });
}

const teTableInfoSchema = z.object({
  table: z.string(),
  exists: z.boolean(),
  rowCount: z.number(),
});
const teTablesSchema = z.array(teTableInfoSchema);
export type TeTableInfo = z.infer<typeof teTableInfoSchema>;

export async function listTeTables(): Promise<TeTableInfo[]> {
  return apiFetch("/api/te/tables", teTablesSchema);
}

export async function previewCsvTable(
  tableName: string,
  limit = 50,
): Promise<{ rows: Record<string, string | number | boolean | null>[] }> {
  return apiFetch(
    `/api/csv/tables/${encodeURIComponent(tableName)}/rows?limit=${limit}`,
    previewRowsSchema,
  );
}
