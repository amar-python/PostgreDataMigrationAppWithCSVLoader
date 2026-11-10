// ─── src/lib/mapping-templates.ts ───────────────────────────────────────────
// Saved header-mapping templates. Stored in localStorage so they persist
// across sessions without a backend.
//
// A template captures: original header names → renamed values, plus the
// column types chosen at preview time. When a file is dropped whose headers
// match a template, the mapping is offered automatically.

import type { ColumnType } from "./csv.functions";
import { dropUnscoped, userKey } from "./user-storage";

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

// Per signed-in tenant and user (#176): templates carry column names and types, which are tenant data.
const BASE = "csv-migrator:mapping-templates";

export function loadTemplates(): MappingTemplate[] {
  try {
    dropUnscoped(BASE);
    const key = userKey(BASE);
    return key ? (JSON.parse(localStorage.getItem(key) ?? "[]") as MappingTemplate[]) : [];
  } catch {
    return [];
  }
}

function store(all: MappingTemplate[]): void {
  const key = userKey(BASE);
  if (key) localStorage.setItem(key, JSON.stringify(all)); // nobody signed in: store nothing
}

export function saveTemplate(t: MappingTemplate): void {
  const all = loadTemplates().filter((x) => x.id !== t.id);
  store([t, ...all]);
}

export function deleteTemplate(id: string): void {
  store(loadTemplates().filter((x) => x.id !== id));
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
  store(loadTemplates().map((t) => (t.id === id ? { ...t, lastUsedAt: Date.now() } : t)));
}
