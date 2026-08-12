## What we're adding

1. **Preview step before import** — after selecting files, show a modal for each file with: detected headers, inferred column types, and the first ~10 sample rows. User clicks **Confirm & Import** or **Cancel**. No editing controls (view-only).

2. **Typed columns** — the per-file table is created with actual Postgres types inferred from the CSV sample (`int8`, `numeric`, `date`, `timestamptz`, `boolean`, `text`), not all-text. Values that don't match their column type are recorded as row errors instead of silently coerced.

3. **Filename duplicate handling** — a duplicate upload is flagged with a note explaining the match (by name or content); the user can rename and retry, or choose **Overwrite** to replace the existing import (see `requestOverwrite`/`DiffDialog`/`confirmOverwrite` in `index.tsx`).

4. **Batch import summary** — a summary card above the jobs list for the current batch: `Files: N` · `Rows processed: N` · `Rows created: N` · `Duplicate rows skipped: N` · `Failed rows: N` · `Duplicate files: N` · `Failed files: N`.

5. **Persist across refresh (localStorage)** — jobs, per-file error rows, and batch summaries are saved to `localStorage` under a versioned key. On reload the jobs list and summary re-hydrate. Any job left in a non-terminal state (`reading`/`uploading`/`processing`) is marked as `interrupted` on hydrate with a note to re-upload. "Clear finished" also clears from storage.

6. **Downloadable error report** — for any `error` or `duplicate` job, an **Export errors** dropdown with **CSV** and **JSON** options. Report includes: file name, row number (or `-` for file-level), raw row snippet, error type, plain-English cause (reuses existing `hintFor()`). Files download as `errors-<filename>-<timestamp>.csv|json`.

## Technical notes

- **Preview**: new `parseCsvPreview(file)` client-side helper returns `{ headers, sampleRows, inferredTypes, totalRowsApprox }`. Type inference walks up to 200 rows per column, picks the narrowest type that fits all non-empty values. Rendered in a shadcn `Dialog`.
- **Typed tables**: extend the `create_csv_table` RPC (migration) to accept `p_columns text[]` **and** `p_types text[]` in the same order, with a whitelist of allowed types. Update `uploadCsv` server fn to pass inferred types and to cast row values; rows that fail casting are collected into a per-row error list returned to the client (row number + column + reason).
- **Row-level errors**: the `uploadCsv` server fn already returns per-file result; extend its return shape to include `rowErrors: { rowNumber, column?, value?, reason }[]`. Store these on the job in localStorage for the error report.
- **Persistence**: `usePersistedJobs()` hook — key `csv-migrator:jobs:v1`, stores serializable job data only (no `File` handles). Interrupted jobs show a "Re-upload to retry" pill instead of the Retry button.
- **Summary**: derived from `jobs` array; a `currentBatchId` groups jobs selected together in one drop/click.
- **Error export**: pure client-side `Blob` + `URL.createObjectURL` download, no backend endpoint.

## Out of scope

- Append mode for duplicate files (overwrite/replace shipped; see F9 in `index.tsx`).
- Editing headers, types, or skipping columns in the preview (view-only).
- Server-side history — persistence is this-browser-only via localStorage.
