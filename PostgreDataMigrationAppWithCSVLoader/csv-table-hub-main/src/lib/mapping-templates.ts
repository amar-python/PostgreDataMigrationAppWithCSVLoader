// ─── src/lib/mapping-templates.ts ───────────────────────────────────────────
// Saved header-mapping templates. Stored in localStorage so they persist
// across sessions without a backend.
//
// A template captures: original header names → renamed values, plus the
// column types chosen at preview time. When a file is dropped whose headers
// match a template, the mapping is offered automatically.

import type { ColumnType } from "./csv.functions";

export type ColumnMapping = {
  /** Original header as parsed from the CSV */
  original: string;
  /** Renamed value the user confirmed; empty string = use sanitised default */
  renamed: string;
  /** Column type chosen in the preview step */
  type: ColumnType;
};

export type MappingTemplate = {
  id: string;
  name: string;
  /** Ordered list matching the source file's column order */
  columns: ColumnMapping[];
  createdAt: number;
  lastUsedAt?: number;
};

const KEY = "csv-migrator:mapping-templates";

export function loadTemplates(): MappingTemplate[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as MappingTemplate[];
  } catch {
    return [];
  }
}

export function saveTemplate(t: MappingTemplate): void {
  const all = loadTemplates().filter((x) => x.id !== t.id);
  localStorage.setItem(KEY, JSON.stringify([t, ...all]));
}

export function deleteTemplate(id: string): void {
  const all = loadTemplates().filter((x) => x.id !== id);
  localStorage.setItem(KEY, JSON.stringify(all));
}

/** Return the best-matching template for a given set of original headers. */
export function findMatchingTemplate(
  originalHeaders: string[],
): MappingTemplate | null {
  const templates = loadTemplates();
  const key = originalHeaders.join(",");
  return (
    templates.find(
      (t) => t.columns.map((c) => c.original).join(",") === key,
    ) ?? null
  );
}

/** Mark a template as used (updates lastUsedAt). */
export function touchTemplate(id: string): void {
  const all = loadTemplates().map((t) =>
    t.id === id ? { ...t, lastUsedAt: Date.now() } : t,
  );
  localStorage.setItem(KEY, JSON.stringify(all));
}
