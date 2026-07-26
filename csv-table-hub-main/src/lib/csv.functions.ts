export type ColumnType =
  | "int8"
  | "numeric"
  | "date"
  | "timestamptz"
  | "boolean"
  | "text";

export type RowError = {
  rowNumber: number;
  column?: string;
  value?: string;
  reason: string;
};

export type ProcessingLog = {
  ts: number;
  step:
    | "receive"
    | "hash"
    | "duplicate_check"
    | "parse"
    | "validate_columns"
    | "create_table"
    | "cast_rows"
    | "insert"
    | "register"
    | "overwrite"
    | "done"
    | "error";
  level: "info" | "warn" | "error";
  message: string;
  count?: number;
  sql?: string;
};

export type UploadResult =
  | {
      status: "ok";
      fileId: string;
      tableName: string;
      totalRows: number;
      insertedRows: number;
      duplicateRowsSkipped: number;
      failedRows: number;
      columns: string[];
      types: ColumnType[];
      rowErrors: RowError[];
      logs: ProcessingLog[];
      overwritten?: boolean;
      replacedFileName?: string;
    }
  | {
      status: "duplicate_file";
      reason: "content" | "name";
      existingFileName: string;
      tableName: string;
      existingRowCount?: number;
      logs: ProcessingLog[];
    }
  | {
      status: "invalid_structure";
      reason: "empty" | "header_only" | "no_columns";
      message: string;
      logs: ProcessingLog[];
    }
  | { status: "error"; message: string; rowErrors?: RowError[]; logs: ProcessingLog[] };

export type CsvFileSummary = {
  id: string;
  file_name: string;
  table_name: string;
  row_count: number;
  column_names: string[];
  created_at: string;
};

const apiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "content-type": "application/json",
    },
    ...options,
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

  return payload as T;
}

export async function uploadCsv(input: {
  fileName: string;
  content: string;
  types?: ColumnType[];
  overwrite?: boolean;
  mode?: "dynamic" | "te";
  targetTable?: string;
}): Promise<UploadResult> {
  return apiFetch<UploadResult>("/api/csv/upload", {
    method: "POST",
    body: JSON.stringify({
      fileName: input.fileName,
      content: input.content,
      types: input.types,
      overwrite: input.overwrite ?? false,
      mode: input.mode ?? "dynamic",
      targetTable: input.targetTable,
    }),
  });
}

export async function listCsvFiles(): Promise<CsvFileSummary[]> {
  return apiFetch<CsvFileSummary[]>("/api/csv/files");
}

export async function previewCsvTable(
  tableName: string,
  limit = 50,
): Promise<{ rows: Record<string, string | number | boolean | null>[] }> {
  return apiFetch<{ rows: Record<string, string | number | boolean | null>[] }>(
    `/api/csv/tables/${encodeURIComponent(tableName)}/rows?limit=${limit}`,
  );
}
