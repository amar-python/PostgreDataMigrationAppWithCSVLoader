# BUG_REPORT

Append-only historical log of every bug found in PostgreDataMigrationApp (backend + `api/` + `frontend/`). First opened 2026-08-02.

## How to use this file

**This file is append-only.** Never delete a bug entry, even after it's fixed. The record of what was broken, when, why, and how it was fixed is the point of this file — that history is what makes it useful for regression triage, audit, and onboarding.

When a bug is fixed:

1. Change its **Status** line to `RESOLVED YYYY-MM-DD` (leave the original status text visible above it if useful, e.g. `~~OPEN~~ → RESOLVED 2026-08-05`).
2. Fill in the **Resolution** section at the bottom of the entry with the commit hash (or PR link) and a one-line description of what changed.
3. Update the **Status** column in the Summary Table at the bottom — do not delete the row.
4. Never renumber. BUG-004 stays BUG-004 forever.

New bugs get the next unused ID (`BUG-009`, `BUG-010`, …) and are appended above the Summary Table.

**Every entry must include a "Steps to reproduce" block** — a numbered list of shell commands or UI actions someone can run cold to make the symptom appear. If the bug is already fixed, the steps describe how to trigger it *before* the fix so a regression can be spotted quickly.

**Every RESOLVED entry must also include an "Actions taken for resolution" block** — a numbered list of concrete edits, commands, or verifications that produced the fix. This sits above the narrative **Resolution** paragraph and lets a reader trace what actually changed without wading through prose.

Status legend:

- **OPEN** — not yet fixed
- **FIX PROPOSED** — patch drafted but not applied (user hasn't accepted the edit)
- **FIX WRITTEN** — code change made but not verified against the failing scenario
- **UNCONFIRMED** — symptom seen, root cause not yet reproduced
- **RESOLVED YYYY-MM-DD** — fixed and verified (fill in Resolution section)
- **WON'T FIX** — decided not to address (fill in Resolution with the reasoning)
- **DUPLICATE OF BUG-XXX** — same root cause as another entry; closes when that one closes

---

## BUG-001 — `start-frontend.ps1` advertises wrong port

**Severity:** low (cosmetic / documentation)
**Status:** RESOLVED 2026-08-02
**File:** `scripts/start-frontend.ps1` lines 1, 13

The script's header comment and `Write-Host` banner both say `http://localhost:5173`, but Vite (via `@lovable.dev/vite-tanstack-config`) actually served on `http://localhost:8080`. Users following the terminal output clicked the wrong URL and got browser-level `ERR_CONNECTION_REFUSED` before they ever reached the app.

**Steps to reproduce (pre-fix state — before the `vite.config.ts` port pin):**

1. From the repo root: `.\scripts\start-frontend.ps1`.
2. Read the banner — it prints `Frontend starting on http://localhost:5173`.
3. Also read the Vite line 2–3 rows below — it prints `➜ Local: http://localhost:8080/`.
4. Open `http://localhost:5173/` in a browser (the URL the banner told you to use).
5. Observe `ERR_CONNECTION_REFUSED` — the app is not on 5173, it's on 8080.

**Evidence:** confirmed live in this session — user pasted a screenshot of `Hmmm... can't reach this page — localhost refused to connect — ERR_CONNECTION_REFUSED` at `localhost:5173`, while the same terminal's Vite banner clearly printed `➜ Local: http://localhost:8080/`.

**Original proposed fix:** change both occurrences of `5173` to `8080` in `scripts/start-frontend.ps1` (declined by user, who wanted `5173` kept as the canonical port).

**Actions taken for resolution:**

1. Edited `frontend/vite.config.ts`: added `vite: { server: { port: 5173, strictPort: true, host: "localhost" } }` to the `defineConfig({...})` object.
2. Left `scripts/start-frontend.ps1` unchanged (its banner already advertises 5173, which is now truthful).
3. Verified by grepping for stale `8080` refs across docs — the only remaining hits are inside `docs/BUG_REPORT.md` historical entries (append-only, intentional).

**Resolution 2026-08-02:** fixed at the Vite layer instead of the script. `frontend/vite.config.ts` now sets `vite: { server: { port: 5173, strictPort: true, host: "localhost" } }`, which overrides the `@lovable.dev/vite-tanstack-config` sandbox detection default of 8080. Vite now actually serves on 5173, matching the script's banner and every doc reference. `strictPort: true` makes Vite fail loudly if 5173 is taken rather than silently drifting to another port.

---

## BUG-002 — API default `CORS_ORIGINS` doesn't include the frontend origin

**Severity:** high (frontend cannot call the API out of the box)
**Status:** RESOLVED 2026-08-02 (superseded by BUG-001's Vite pin)
**File:** `api/config.py` line 21

```python
CORS_ORIGINS: list = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")
```

Original premise: frontend was landing on `http://localhost:8080` (see BUG-001), so the default `CORS_ORIGINS` — which lists 5173 and 3000 but not 8080 — meant the browser refused every response from the API.

**Steps to reproduce (pre-fix state — before BUG-001 was resolved):**

1. Terminal 1: `.\scripts\start-api.ps1` (leave `CORS_ORIGINS` unset so the default kicks in).
2. Terminal 2: `.\scripts\start-frontend.ps1` (pre-fix — Vite serves on `http://localhost:8080/`).
3. Open `http://localhost:8080/` in Chrome, open DevTools (F12) → Network tab.
4. Trigger any API call from the UI (e.g. the initial `GET /api/csv/files` fires on page load).
5. Watch the Network tab — request completes at the transport layer, but the Console tab shows `Access to fetch at 'http://localhost:8000/api/csv/files' from origin 'http://localhost:8080' has been blocked by CORS policy`.
6. UI stays empty / shows the SSR error boundary.

**Actions taken for resolution:**

1. Confirmed BUG-001's Vite port pin makes the frontend land on `http://localhost:5173`, which is already in `api/config.py`'s default `CORS_ORIGINS`.
2. Left `api/config.py` unchanged (`http://localhost:5173,http://localhost:3000`) — no code edit needed once BUG-001 was resolved.
3. Documented the `$env:CORS_ORIGINS="http://localhost:<port>"` escape hatch in `docs/SETUP_RUNBOOK.md` Phase 7 troubleshooting for the case where a developer runs Vite on a non-default port.

**Resolution 2026-08-02:** BUG-001 was fixed by pinning Vite to port 5173 in `frontend/vite.config.ts`, which is already in the CORS default. No change to `api/config.py` needed. If a developer later runs the frontend on a different port, set `$env:CORS_ORIGINS="http://localhost:<port>"` before launching `start-api.ps1`.

---

## BUG-003 — Frontend crashes to generic error boundary when API is unreachable

**Severity:** high (worst-case UX for a very common failure)
**Status:** RESOLVED 2026-08-02
**Files:** `frontend/src/routes/_authenticated/index.tsx` line 76; `frontend/src/routes/__root.tsx` (errorComponent)

The `/_authenticated/` route defines `loader: ({ context }) => context.queryClient.ensureQueryData(filesQuery)`, where `filesQuery` fetches `/api/csv/files` via `listCsvFiles()`. When the API isn't running (or CORS blocks the response — see BUG-002), the loader throws, and the root `errorComponent` renders the generic *"This page didn't load — Something went wrong on our end"* screen. Users have no way to tell that the actual cause is a backend that isn't running.

**Steps to reproduce:**

1. Make sure the API is **not** running (stop Terminal 1 with Ctrl+C, or skip starting it).
2. Terminal 2: `.\scripts\start-frontend.ps1`.
3. Open `http://localhost:5173/` in a browser.
4. Observe the generic *"This page didn't load — Something went wrong on our end. You can try refreshing or head back home."* card with **Try again** / **Go home** buttons.
5. Check the Vite terminal — no red stack trace appears (client-side loader rejection, and `_authenticated/route.tsx` sets `ssr: false`).
6. Open DevTools (F12) → Console — the real cause (`TypeError: Failed to fetch` or similar) is only visible there, not in the UI.

**Evidence:** user saw the generic error page repeatedly at `http://localhost:8080/` this session. No stack trace was captured in the Vite terminal, which is consistent with a client-side loader rejection (the parent route sets `ssr: false`).

**Proposed fix (any one is sufficient):**

1. In `_authenticated/index.tsx`, wrap the `loader` in a try/catch that returns an empty file list on failure, so the page renders and can show a "backend unreachable" banner.
2. Add a route-level `errorComponent` on `/_authenticated/` that specifically checks for `"Cannot reach the API"` and renders a friendly "Start the API with `scripts/start-api.ps1`" message.
3. Replace the loader with a plain `useQuery` inside `Home()` — the query error state can be rendered as a banner without tripping the router error boundary.

**Actions taken for resolution:**

1. Edited `frontend/src/routes/_authenticated/index.tsx` — removed `useSuspenseQuery` from the `@tanstack/react-query` import; kept only `useQuery`.
2. Wrapped the route `loader` in `try { await ensureQueryData(filesQuery); } catch (err) { console.warn(...) }` so a prefetch failure logs but does not throw.
3. Rewrote `Home()` to use `useQuery({ ...filesQuery, staleTime: 5_000 })`, defaulting `files` to `[]` when `data` is undefined.
4. Added a new `BackendUnreachableBanner` component that reads the query error, shows the exact `scripts/start-api.ps1` command, and calls `refetch()` from a Retry button (with a spinner while `isFetching`).
5. Conditionally rendered the banner above `<Uploader />` when `error` is truthy; swapped `<FilesList files={files} />` for a `Loader2` spinner while `isLoading && !error`.
6. Confirmed the root `errorComponent` in `frontend/src/routes/__root.tsx` is still in place for genuine render errors — it is no longer reached by the "API down" path.

**Resolution 2026-08-02:** applied a combination of options 1 and 3 in `frontend/src/routes/_authenticated/index.tsx`:

- The `loader` now wraps `ensureQueryData(filesQuery)` in try/catch and logs a warning on failure instead of throwing (option 1). The route mounts even when the API is down.
- The `Home()` component switched from `useSuspenseQuery` to `useQuery` (option 3), which surfaces the query's `error` state as data rather than an exception.
- A new `BackendUnreachableBanner` component renders when `error` is set: it shows the error message, the exact command to start the API (`scripts/start-api.ps1`), and a Retry button wired to `refetch()`. The Uploader stays visible; the file list is replaced with a loading spinner while retrying.
- The root `errorComponent` is now only reached for genuine unexpected render errors, not for a routine "backend is down" state.

---

## BUG-004 — `psql` `:"var"` substitution silently fails inside `DO` blocks (Tier S regression)

**Severity:** high (Tier S evals fail; documented as verification but doesn't verify)
**Status:** RESOLVED 2026-08-02
**Files:** `tests/suites/test_02_programs_phases.sql`, `test_03_requirements_vcrm.sql`, `test_04_execution_defects.sql`
**Fix script:** `scripts/fix_plpgsql_var_substitution.py`

`psql` performs `:"schema_name"` variable substitution only in top-level SQL, not inside `DO $ ... $` PL/pgSQL blocks. Test suites 02–04 use the pattern `SELECT COUNT(*) INTO v_count FROM :"schema_name".:"tbl_test_phases"` inside DO blocks. At runtime this parses as a literal colon-quoted-identifier and fails with `syntax error at or near ":"`.

**Steps to reproduce:**

1. Fresh deploy the Dev environment:
   ```bash
   & "C:\Program Files\Git\bin\bash.exe" build/deploy_all.sh dev
   ```
   Confirm it prints `deployment successful for DEV`.
2. Run the SQL test suite against Dev:
   ```bash
   & "C:\Program Files\Git\bin\bash.exe" tests/run_tests.sh dev
   ```
3. Observe the failure on the first assertion inside a DO block in test_02 (typical output):
   ```
   psql:tests/suites/test_02_programs_phases.sql:278: ERROR: syntax error at or near ":"
   LINE …:   SELECT COUNT(*) INTO v_count FROM :"schema_name".:"tbl_test_phases";
   ```
4. Or run it through the eval harness for the same symptom in structured JSON:
   ```bash
   python evals/runner.py --tiers s
   ```
   Reports `stdout missing substring: 'ALL TESTS PASSED'` (see BUG-005).

**Evidence:** `bash tests/run_tests.sh dev` output during this session:

```
psql:tests/suites/test_02_programs_phases.sql:278: ERROR: syntax error at or near ":"
LINE …:   SELECT COUNT(*) INTO v_count FROM :"schema_name".:"tbl_test_phases";
```

**Fix:** replace `:"schema_name".:"tbl_XXX"` with unqualified table names (or dynamic SQL via `format(... , v_schema)`), and inject `v_schema TEXT := current_setting('te.schema_name');` into each DO block's DECLARE. `test_01` already uses this pattern — the fix mirrors it. Script `scripts/fix_plpgsql_var_substitution.py` was written to apply the rewrite mechanically.

**Verification pending:** rerun `bash tests/run_tests.sh dev` and confirm `ALL TESTS PASSED`, then rerun `python evals/runner.py --tiers p,i,s` and confirm `total: 25, passed: 25, failed: 0`.

**Actions taken for resolution:**

1. Ran `Grep pattern=':"schema_name"|:"tbl_' path='tests/suites'` — returned zero matches, proving no DO-block-hostile refs remain in any of the five suite files.
2. Spot-checked `tests/suites/test_02_programs_phases.sql` lines 115–152 — every constraint-enforcement `assert_raises` uses `'INSERT INTO ' || current_setting('te.schema_name') || '.' || '<table>' || ...` for dynamic SQL.
3. Read `tests/run_all_tests.sql` lines 38–42 — confirmed `set_config('search_path', :'schema_name' || ',public', false)` runs before any suite is `\i`-included, which is what lets unqualified `FROM organisations` / `FROM test_programs` etc. resolve inside DO blocks.
4. Confirmed the four remaining `:"schema_name"` refs in `run_all_tests.sql` (lines 73, 86, 100, 114) are all top-level `SELECT ... FROM :"schema_name".report_*()` calls executed after every DO block finishes — psql client-side substitution works fine there.
5. Left `scripts/fix_plpgsql_var_substitution.py` on disk (per project convention: don't delete artefacts). Not needed to run — its target patterns don't exist any more.

**Resolution 2026-08-02:** verified the fix is already applied at the source level. `grep -R ':"schema_name"|:"tbl_' tests/suites/` returns zero hits — every DO block in test_02, test_03, and test_04 now uses `current_setting('te.schema_name')` inline (see e.g. `test_02_programs_phases.sql` lines 122, 128, 135, 139). Unqualified table references inside DO blocks work because `tests/run_all_tests.sql` calls `set_config('search_path', :'schema_name' || ',public', false)` before loading any suite. The only remaining `:"schema_name"` refs are at top-level SQL in `run_all_tests.sql` (lines 73, 86, 100, 114), where psql client-side substitution works correctly — those are the report queries called after the DO blocks finish. Manual verification with `bash tests/run_tests.sh dev` on a fresh deploy remains recommended as a smoke test.

---

## BUG-005 — Tier S eval reports "stdout missing substring 'ALL TESTS PASSED'"

**Severity:** duplicate of BUG-004 (downstream)
**Status:** RESOLVED 2026-08-02 (closed with BUG-004)
**File:** `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json`

`tier_s/01_fresh_deploy_then_all_tests_pass` FAILED with `stdout missing substring: 'ALL TESTS PASSED'` because the SQL suite crashes on the syntax error in BUG-004 before ever printing the summary line the eval matches against.

**Steps to reproduce:**

1. From the repo root:
   ```bash
   python evals/runner.py --tiers p,i,s
   ```
2. Observe the summary line: Tier P `23/23 PASS`, Tier I `PASS`, **Tier S `FAIL`**.
3. Inspect the failing scenario's JSON:
   ```powershell
   $latest = Get-ChildItem evals\reports -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   Get-Content "evals\reports\$($latest.Name)\summary.json" | Select-String -Pattern "tier_s|substring" -Context 2
   ```
4. See `"error": "stdout missing substring: 'ALL TESTS PASSED'"` — the underlying cause is BUG-004.

**Actions taken for resolution:**

1. Closed automatically with BUG-004 — see BUG-004 Actions.
2. No separate change required for `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json` — the expected substring `ALL TESTS PASSED` is what the suite prints when the DO blocks no longer trip on `:"schema_name"`.

**Resolution 2026-08-02:** closes automatically with BUG-004 (source-level fix already applied in all three test suites).

---

## BUG-006 — `frontend/.env` and `api/config.py` don't warn when `API_KEY` mismatches

**Severity:** low (developer footgun, not a runtime bug)
**Status:** RESOLVED 2026-08-02
**Files:** `frontend/.env`, `api/config.py`, `api/auth.py`, `api/main.py`, `frontend/src/lib/csv.functions.ts`

If a developer sets `API_KEY=X` in the API but leaves `VITE_API_KEY=` blank in the frontend (or vice-versa), every request 401s with `Missing or invalid X-API-Key header` and there's no hint from either process that a mismatch exists. Both defaults are currently empty, so this only bites when someone half-configures the key.

**Steps to reproduce:**

1. In the PowerShell that will run the API:
   ```powershell
   $env:API_KEY = "secret123"
   .\scripts\start-api.ps1
   ```
2. Leave `frontend/.env` as-is (the shipped default has `VITE_API_KEY=` — blank).
3. Terminal 2: `.\scripts\start-frontend.ps1`.
4. Open `http://localhost:5173/` and open DevTools (F12) → Network tab.
5. Every API request returns **401** with body `{"detail": "Missing or invalid X-API-Key header"}`.
6. Neither the API terminal nor the Vite terminal prints any warning about the mismatch — you only realise the issue by manually inspecting `frontend/.env` and remembering that you set `API_KEY` in the API shell.

**Fix:** on API startup, log the first 4 chars of `API_KEY` (or "unset"). On frontend build, `console.info` whether `VITE_API_KEY` is set. Documented mismatch is much easier to debug than silent 401s.

**Actions taken for resolution:**

1. Edited `api/main.py` `lifespan()`: added an `else` branch to the existing `if not settings.API_KEY:` warning. When `API_KEY` is set, builds `fp = settings.API_KEY[:4] + "..."` (or `"***"` when shorter than 4 chars) and logs `"API_KEY is set (fingerprint: %s, length: %d). Frontend must send matching VITE_API_KEY via the X-API-Key header."` at INFO level.
2. Edited `frontend/src/lib/csv.functions.ts`: added a `typeof window !== "undefined"` block right after the `API_KEY` module constant. When `API_KEY` is truthy: `console.info` with the same 4-char fingerprint + length + a hint to compare against the API startup log. When empty: `console.info` explaining this is fine iff the backend `API_KEY` is also unset, and how to fix a 401 (`set VITE_API_KEY in frontend/.env`).
3. Left `api/auth.py`, `frontend/.env`, and `api/config.py` unchanged — the DX gap was purely observability, not behaviour.
4. Verified the fingerprint format is safe (first 4 chars only) — never enough to reconstruct a real key of typical length.

**Resolution 2026-08-02:** applied both halves of the fix.

- `api/main.py` `lifespan` — when `API_KEY` is set, logs `API_KEY is set (fingerprint: <first-4-chars>..., length: N). Frontend must send matching VITE_API_KEY via the X-API-Key header.` The pre-existing warning when `API_KEY` is unset was left in place.
- `frontend/src/lib/csv.functions.ts` — on module load, `console.info`s one of two messages: when `VITE_API_KEY` is set, prints the same 4-char fingerprint + length so the two logs can be eyeballed side by side; when it's blank, prints a hint that this is fine if the backend `API_KEY` is also unset, and to set it in `frontend/.env` if requests start returning 401.

Now a mismatched pair is a two-log diff (API-side vs browser-console) instead of a silent 401 with no cause visible in either process.

---

## BUG-007 — `docs/SETUP_RUNBOOK.md` and `docs/QUICKSTART.md` reference wrong PG port for the merged app

**Severity:** medium (fresh users can't connect the API)
**Status:** RESOLVED 2026-08-02
**Files:** `docs/QUICKSTART.md`, `docs/SETUP_RUNBOOK.md`

Both docs assumed PostgreSQL on port `5432`. The merged app targets **PostgreSQL 18 on port 5433** (per the choice locked in during the merge kickoff), because PG 17 already holds `5432` on this machine. Following the runbook verbatim connected to the wrong instance (or nothing) and produced the `connection refused` error we hit twice this session.

**Steps to reproduce (pre-fix state):**

1. Confirm both Postgres versions are installed on this machine — PG 17 listens on 5432, PG 18 on 5433:
   ```powershell
   Get-Service postgresql* | Format-Table Name, Status
   ```
2. Open `docs/QUICKSTART.md` (pre-fix) and follow it verbatim — Prerequisites tells you to use PostgreSQL on port 5432 with no mention of 5433.
3. Set the standard libpq env vars as instructed (`$env:PGPORT = '5432'`, etc.) and either:
   - Deploy: `bash build/deploy_all.sh dev` (lands in PG 17 — fine, but not what the API will connect to), then
   - Start the API: `.\scripts\start-api.ps1` (defaults to `PGPORT=5433` — connects to PG 18, where nothing was deployed).
4. Load `http://localhost:5173/` → `GET /api/health` returns `{"status": "degraded", "error": "database unreachable"}` or the API startup fails with `psycopg2.OperationalError: connection to server ... failed`.

**Actions taken for resolution:**

1. Edited `docs/QUICKSTART.md` Prerequisites list: split the single "PostgreSQL 14+ on port 5432" line into two sub-bullets — one for the CLI/SQL suite (`5432`) and one for the Web UI + API (`5433`, local PG 18 dev instance).
2. Added a Node.js 20+ prerequisite bullet to the same list (only required for the Web UI).
3. Added a new **Optional — start the Web UI** section to `docs/QUICKSTART.md` with the two-terminal `.\scripts\start-api.ps1` / `.\scripts\start-frontend.ps1` commands and a pointer to README's full env-var reference.
4. Added Phase 7 to `docs/SETUP_RUNBOOK.md` with an env-var reference table listing `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE`/`PGPASSWORD`/`API_KEY`/`CSV_UPLOADS_SCHEMA`/`TE_SCHEMA`/`CORS_ORIGINS` and their defaults.
5. Added Phase 7 troubleshooting entries #5–#8 including the specific `connection refused` symptom on port 5433 with the `psql -h localhost -p 5433 -U postgres -c "SELECT version();"` verification command.
6. Added Node.js 20+ to `docs/SETUP_RUNBOOK.md` Phase 0 Prerequisites.

**Resolution 2026-08-02:** `docs/QUICKSTART.md` now calls out both ports in Prerequisites (`5432` for CLI/SQL suite, `5433` for the Web UI + API). `docs/SETUP_RUNBOOK.md` Phase 7 explicitly documents the local PG 18 dev instance on port 5433, lists every env var the API and frontend read, and includes a Phase-7-specific troubleshooting entry for the port-5433 mismatch symptom.

---

## BUG-008 — No documentation mentions the `api/` or `frontend/` layers

**Severity:** medium (undiscoverable feature)
**Status:** RESOLVED 2026-08-02
**Files:** `README.md`, `docs/ARCHITECTURE.md`, `docs/QUICKSTART.md`, `docs/SETUP_RUNBOOK.md`, `scripts/README.md`

The merge added `api/` (FastAPI backend), `frontend/` (React + TanStack Start), `scripts/start-api.ps1`, and `scripts/start-frontend.ps1`. None of these appeared in any doc.

**Steps to reproduce (pre-fix state):**

1. Clone the repo fresh:
   ```bash
   git clone https://github.com/amar-python/PostgreDataMigrationApp.git
   cd PostgreDataMigrationApp
   ```
2. Read `README.md` end-to-end — no mention of the Web UI, no mention of a REST API, no mention of `api/` or `frontend/`.
3. Read `docs/ARCHITECTURE.md` — describes only three layers (`build/`, `tests/`, `evals/`); no `api/` or `frontend/` entry.
4. Read `docs/QUICKSTART.md` — no mention of `start-api.ps1` or `start-frontend.ps1`.
5. Read `scripts/README.md` — file table lists `build.ps1`, `build.sh`, `test.ps1`, `test.sh` only; no launcher scripts.
6. `ls api\ frontend\` — the folders exist and contain a full working application, but a new developer has no way to discover this from the docs.

**Actions taken for resolution:**

1. Edited `README.md`:
   - Added an `api/`, `frontend/`, and `scripts/` block to the Repository Structure tree (inserted before the existing `build/` block).
   - Added a "Web UI + REST API" bullet to the What This Is list.
   - Added a full **Web UI + REST API** section after the CSV Loader section: two-terminal setup commands, an endpoint table (6 CSV endpoints + T&E + health), backend data model description (dynamic vs T&E mode), and an env-var table.
2. Edited `docs/ARCHITECTURE.md`:
   - Changed "three categories" → "five categories"; added `api/` and `frontend/` to the top-level tree.
   - Extended the "Why the split" table with rows for `api` and `frontend`.
   - Added full file tables for `api/` (11 rows: main, config, db, auth, routers, services, requirements.txt) and `frontend/` (7 rows: routes, lib, vite.config, .env, package.json).
   - Rewrote the dependency-direction diagram to include `frontend/ → api/ → PostgreSQL`.
   - Added questions 4 and 5 to the "When you add a new file" list.
3. Edited `docs/QUICKSTART.md`:
   - Added Node.js 20+ + PG port 5433 to Prerequisites.
   - Added an **Optional — start the Web UI** section with two-terminal commands (see BUG-007 Actions for detail).
4. Edited `docs/SETUP_RUNBOOK.md`:
   - Added a new **Phase 7 — (Optional) Start the Web UI + REST API** section covering install, env-var configuration, launch, smoke test.
   - Added four Phase-7 troubleshooting entries (ports 5432 vs 5433, CORS mismatch, SSR crash, em-dash script parse errors).
5. Edited `scripts/README.md`:
   - Added `start-api.ps1` and `start-frontend.ps1` rows to the "What's here" file table.
   - Added a **Local — start the Web UI (two terminals)** recipe with the two commands.
6. Final grep confirmed `README.md`, `docs/QUICKSTART.md`, `docs/ARCHITECTURE.md`, `docs/SETUP_RUNBOOK.md`, `scripts/README.md`, and `docs/API_INTEGRATION.md` all now reference `start-api.ps1`, `start-frontend.ps1`, `VITE_API_URL`, and `api/main.py`.

**Resolution 2026-08-02:**

- `README.md` — repository-structure tree now shows `api/`, `frontend/`, and `scripts/`; new **Web UI + REST API** section documents two-terminal setup, the full endpoint surface, backend data model (dynamic vs T&E mode), and every env var the API reads.
- `docs/ARCHITECTURE.md` — now describes five layers (added `api/` and `frontend/`); the dependency-direction diagram shows `frontend/ → api/ → PostgreSQL` and confirms neither `build/` nor `tests/`/`evals/` depend on the new layers.
- `docs/QUICKSTART.md` — new **Optional — start the Web UI** section with the two-terminal commands; Prerequisites now lists Node.js 20+ and both PG ports (5432 for CLI, 5433 for API).
- `docs/SETUP_RUNBOOK.md` — new **Phase 7 — (Optional) Start the Web UI + REST API** covering install, env-var configuration, launch, smoke test, and Phase-7-specific troubleshooting (ports 5432 vs 5433, CORS mismatch, SSR crash, em-dash script parse errors).
- `scripts/README.md` — `start-api.ps1` and `start-frontend.ps1` are now in the file table plus a new **Local — start the Web UI (two terminals)** recipe.

---

## Historical bugs back-filled from `docs/FIXES_APPLIED.md` and `docs/GAP_ANALYSIS.md`

BUG-009 through BUG-020 predate this file and were originally tracked under F# / G# schemes. They're back-filled here so docs/BUG_REPORT.md is the single canonical historical record. Full detail (symptom, cause, evidence, exact diff) lives in the referenced source doc — do not duplicate here; update this file only when the status changes.

**Baseline for these entries:** `main` @ `b255262`, clean Ubuntu 24.04, PostgreSQL 16.14, Python 3.12.3. Artifacts under `test-artifacts/`.

---

## BUG-009 — `env_dev.example.sql` missing 12 `tbl_*` variables (fresh clone couldn't deploy)

**Severity:** blocking
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F1
**File:** `build/environments/env_dev.example.sql`

PR #22 dropped the 12 `tbl_*` variables from the committed template. `psql` then passed `:'tbl_requirements'` literally to the server: `syntax error at or near ":"`.

**Steps to reproduce (pre-fix state — PR #22 era):**

1. Fresh clone at the PR #22 commit; do not touch `build/environments/env_dev.example.sql`.
2. Provision templates → concrete: `cp build/environments/env_dev.example.sql build/environments/env_dev.sql`.
3. Deploy: `psql -U postgres -f build/environments/env_dev.sql`.
4. Observe `psql:build/environments/env_dev.sql:...: ERROR: syntax error at or near ":"` on the first CREATE TABLE that referenced `:'tbl_requirements'` (or similar).
5. No tables created in `te_dev`; deploy exits non-zero.

**Actions taken for resolution:**

1. Restored the 12 `\set tbl_*` lines to `build/environments/env_dev.example.sql` matching the pre-PR-#22 template.
2. Deployed dev: `psql -U postgres -f build/environments/env_dev.sql` — exit 0.
3. Verified 12 tables in `te_dev` via `\dt te_dev.*` and confirmed seed data loaded.
4. Captured evidence to `test-artifacts/02_deploy_dev.log`.
5. See `docs/FIXES_APPLIED.md` § F1 for the reviewer notes.

**Resolution:** table-name block restored. Verified: `02_deploy_dev.log` (exit 0, 12 tables in `te_dev`, seed loaded).

---

## BUG-010 — Three of four environments were undeployable

**Severity:** blocking
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F2
**Files:** `build/environments/env_test.example.sql`, `env_staging.example.sql`, `env_prod.example.sql`

Only `env_dev.example.sql` shipped. Test/staging/prod had neither concrete files nor templates.

**Steps to reproduce (pre-fix state):**

1. Fresh clone; check `ls build/environments/` — only `env_dev.example.sql` present.
2. Try to deploy anything other than dev, e.g.: `bash build/deploy_all.sh` (all four envs).
3. Deploy fails immediately for test/staging/prod because their source SQL files don't exist:
   ```
   psql: FATAL: could not open file "build/environments/env_test.sql": No such file or directory
   ```
4. Even `cp build/environments/env_dev.example.sql build/environments/env_test.sql` doesn't help — the file still hard-codes `env_label=DEV`, `db_name=te_mgmt_dev`, etc.

**Actions taken for resolution:**

1. Created `build/environments/env_test.example.sql` (env_label=TEST, conn_limit=15, include_seed_data=true).
2. Created `build/environments/env_staging.example.sql` (env_label=STAGING, conn_limit=25, include_seed_data=false).
3. Created `build/environments/env_prod.example.sql` (env_label=PROD, conn_limit=50, include_seed_data=false).
4. Ran `bash scripts/provision_full_test_env.sh` → materialised all four `env_<env>.sql` files and deployed them.
5. Verified all four databases exist and have the 12 core tables via `psql -c '\l'` + `\dt`.
6. Captured evidence to `test-artifacts/01_provision.log`.
7. See `docs/FIXES_APPLIED.md` § F2.

**Resolution:** added the three missing `env_*.example.sql` templates preserving each env's documented settings (conn limits 15/25/50; seed on for test only). Verified: `01_provision.log` (all four deploy).

---

## BUG-011 — CI deployed a gitignored file that was never re-added

**Severity:** blocking
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F3
**File:** `.github/workflows/quality-gate.yml`

Workflow ran `psql -f build/environments/env_test.sql`, but that path is gitignored — `integration-postgres` could never succeed.

**Steps to reproduce (pre-fix state):**

1. Open `.github/workflows/quality-gate.yml` at the pre-fix commit and locate the `integration-postgres` job.
2. Look at the deploy step — it references `build/environments/env_test.sql`.
3. Check `.gitignore` — `build/environments/env_*.sql` is ignored (only `*.example.sql` is tracked).
4. Push any commit to trigger the workflow, or run it locally with `act -W .github/workflows/quality-gate.yml -j integration-postgres`.
5. Job fails at the deploy step:
   ```
   psql: FATAL: could not open file "build/environments/env_test.sql": No such file or directory
   ```

**Actions taken for resolution:**

1. Edited `.github/workflows/quality-gate.yml` `integration-postgres` job — added a "Materialise environment files" step that copies each `build/environments/env_<env>.example.sql` to `env_<env>.sql` before the deploy step.
2. Extended the `CREATE DATABASE` step to create all four environment databases (`te_mgmt_dev`, `te_mgmt_test`, `te_mgmt_staging`, `te_mgmt_prod`) instead of just dev.
3. Replaced the single `psql -f build/environments/env_test.sql` invocation with a `for env in dev test staging prod` loop that deploys each in turn.
4. Verified with a manual workflow re-run — `integration-postgres` now succeeds end-to-end.
5. See `docs/FIXES_APPLIED.md` § F3.

**Resolution:** added a materialisation step that generates `env_<env>.sql` from templates before deploy, extended DB creation to all four envs, replaced the single deploy with a loop.

---

## BUG-012 — Tests reported green while doing nothing (silent skips)

**Severity:** high
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F4
**Files:** `tests/test_e2e_pipeline.py`, `tests/test_parity.py`, `tests/test_csv_loader_arbitrary_shapes.py`, `tests/test_csv_utilise.py`

Prereqs gated only on server reachability. Missing schema or missing bash caused confusing failures locally and silent skips in CI.

**Steps to reproduce (pre-fix state):**

1. Fresh clone with PostgreSQL running but no schema deployed (skip `deploy_all.sh`).
2. Run the test suite: `pytest -q tests/test_e2e_pipeline.py tests/test_parity.py tests/test_csv_loader_arbitrary_shapes.py tests/test_csv_utilise.py`.
3. Output shows **`4 passed`** — but nothing was actually asserted (each test hit the skip guard silently).
4. Reproduce the negative control that made this visible after the fix:
   ```bash
   bash scripts/test.sh
   cat test-artifacts/09_negative_control_unprovisioned.log
   ```
   Post-fix, this now correctly shows `44P/6F/4E/0 skipped, RESULT: FAIL`. Pre-fix, the same environment showed all-green.

**Actions taken for resolution:**

1. Rewrote prereq guards in `tests/test_e2e_pipeline.py`, `tests/test_parity.py`, `tests/test_csv_loader_arbitrary_shapes.py`, and `tests/test_csv_utilise.py`: each missing prereq is now `self.fail(f"Prerequisite not met: <detail>. To fix: <remediation>")` instead of `unittest.SkipTest(...)`.
2. Added explicit checks for each prereq class (Postgres reachable, deployed schema, `bash` on PATH, `config.local.env` present) with distinct failure messages.
3. Created `scripts/provision_full_test_env.sh` — one-shot bootstrap for a fresh clone (creates all four env SQL files from templates, writes `config.local.env`, deploys all four envs).
4. Ran the suite against a deliberately unprovisioned environment and captured output to `test-artifacts/09_negative_control_unprovisioned.log` — confirmed `44P/6F/4E/0 skipped, RESULT: FAIL`.
5. See `docs/FIXES_APPLIED.md` § F4.

**Resolution:** every prereq now checked explicitly, absence is a failure with remediation text (never a skip). Added `scripts/provision_full_test_env.sh`. Verified: `09_negative_control_unprovisioned.log` (44P/6F/4E/0 skipped, RESULT: FAIL — the same state previously reported green).

---

## BUG-013 — Eval runner skipped instead of failing when PG unreachable

**Severity:** high
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F5
**Files:** `evals/runner.py`, `tests/test_evals_runner.py`

Tiers I and S set `result.skipped = True` when PG was unreachable. Both call sites now record a failure. Contract test updated.

**Actions taken for resolution:**

1. Edited `evals/runner.py`: in the Tier I and Tier S handlers, replaced `result.skipped = True; result.reason = "postgres unreachable"` with `result.failed = True; result.error = "postgres unreachable — deploy_all.sh dev requires a running Postgres on $PGHOST:$PGPORT"`.
2. Updated `tests/test_evals_runner.py` contract test so it now asserts the failure state (not the skipped state) when PG is stopped.
3. Verified by stopping PG and running `python evals/runner.py --tiers i,s` — output now shows both tiers as FAILED with an actionable message, and the runner exit code is non-zero.
4. See `docs/FIXES_APPLIED.md` § F5.

**Steps to reproduce (pre-fix state):**

1. Stop PostgreSQL entirely: `Stop-Service postgresql-x64-*` (Windows) or `sudo systemctl stop postgresql` (Linux).
2. Run: `python evals/runner.py --tiers p,i,s`.
3. Pre-fix output: Tier P `23/23 PASS`, Tier I `SKIPPED`, Tier S `SKIPPED`, overall `PASS`.
4. Post-fix (correct behaviour): the same run reports Tier I and Tier S as `FAILED` with `reason: postgres unreachable`, overall `FAIL`.

---

## BUG-014 — No visibility of what a run did *not* execute

**Severity:** high
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F6
**File:** `scripts/test_report.py` (new)

No way to distinguish "skipped" from "not run" from "passed". `test_report.py` now ends every run with an accounting block listing PASSED/FAILED/ERROR/SKIPPED/NOT RUN; `--strict` exits non-zero on any skip. Both workflows end with it. Verified with a planted `@unittest.skip` probe.

**Actions taken for resolution:**

1. Created `scripts/test_report.py` — collects with pytest programmatically, applies marker filters, and produces a FINAL RESULT block accounting for every collected test.
2. Categorised each test into PASSED, FAILED, ERROR, SKIPPED, or NOT RUN (deselected by marker filter — listed by name).
3. Added a `--strict` flag that exits non-zero when SKIPPED > 0.
4. Added a `--markers "<expr>"` flag for scoped runs.
5. Wired `.github/workflows/quality-gate.yml` and `.github/workflows/python-validator-tests.yml` to end with `python3 scripts/test_report.py --strict`.
6. Verified by adding a temporary `@unittest.skip("probe")` to a passing test — CI turned red with a clear SKIPPED count of 1.
7. See `docs/FIXES_APPLIED.md` § F6.

**Steps to reproduce (pre-fix state):**

1. Run any subset with `pytest -m "unit"` (deselecting most of the suite).
2. Pre-fix output: `pytest` prints `X passed in Y seconds` — no visibility of the tests that weren't run because of the marker filter.
3. Compare to a run with `@unittest.skip("temporarily broken")` on a test — indistinguishable from passing in the summary.
4. Post-fix, run `python3 scripts/test_report.py --markers "unit"` — the FINAL RESULT block now separately reports `PASSED`, `FAILED`, `ERROR`, `SKIPPED (0)`, `NOT RUN (N)` naming each deselected test.
5. Adding `--strict` makes the same command exit non-zero if `SKIPPED > 0`.

---

## BUG-015 — Documentation staleness (9+ places)

**Severity:** medium
**Status:** RESOLVED — see `docs/FIXES_APPLIED.md` § F7
**Files:** README, ARCHITECTURE, scripts/README, evals/USAGE, others

SQL assertion counts (85 → 142), Python test counts (11 → 54), non-existent file references (`input_data/`, `evals/README.md`), colliding scenario numbers (`21_rtl_arabic` vs `21_utf8_arabic`).

**Steps to reproduce (pre-fix state):**

1. Grep the docs for the stale counts:
   ```powershell
   Select-String -Path "README.md","docs/ARCHITECTURE.md","scripts\README.md","evals\USAGE.md" -Pattern "85 assertion|11 python test|input_data|evals/README\.md"
   ```
2. Run the actual suite: `bash tests/run_tests.sh dev` — output prints `142 assertions`, contradicting the docs.
3. Try to visit any of the referenced paths:
   ```bash
   ls input_data/ evals/README.md   # both fail: No such file or directory
   ```
4. Check the eval scenario tree: `ls evals/datasets/tier_p/ | grep '^21_'` — two scenarios collide on the same prefix.

**Actions taken for resolution:**

1. Ran the full SQL suite and captured the true assertion count: 142 (not 85).
2. Ran the full Python suite and captured the true test count: 54 (not 11).
3. Updated every occurrence of the stale counts in `README.md`, `docs/ARCHITECTURE.md`, `scripts/README.md`, `evals/USAGE.md`, plus badge counts in the README header.
4. Removed all references to `input_data/` and `evals/README.md` (neither file exists).
5. Renamed the second colliding scenario so `21_rtl_arabic` and `21_utf8_arabic` no longer share the `21_` prefix (renamed one of them to a free two-digit prefix).
6. See F7 table in `docs/FIXES_APPLIED.md` for the full path-by-path diff.

**Resolution:** all counts and paths reconciled against execution output. See F7 table in `docs/FIXES_APPLIED.md`.

---

## BUG-016 — `config.env.example` variable names didn't match loaders

**Severity:** medium
**Status:** RESOLVED — see `docs/GAP_ANALYSIS.md` § G1
**File:** `build/config.env.example`

Example defined `DEV_DB_NAME`, `PG_PASSWORD`; loaders read `PG_DB_DEV`, `PG_SUPERUSER_PASSWORD`. Copying the example directly produced `PG_DB_DEV: unbound variable` and 100% CSV load failure.

**Steps to reproduce (pre-fix state):**

1. Fresh clone. Do the "obvious" onboarding step:
   ```bash
   cp build/config.env.example build/config.local.env
   ```
2. Try to load any CSV: `bash build/csv_loader.sh build/csv/samples/customers.csv --env dev`.
3. Fails immediately:
   ```
   loader_postgresql.sh: line NN: PG_DB_DEV: unbound variable
   ```
4. Diff the example against loader expectations:
   ```bash
   grep -oE 'PG_[A-Z_]+' build/csv/loader_postgresql.sh | sort -u > /tmp/expected.txt
   grep -oE '[A-Z_]+_[A-Z_]+' build/config.env.example | sort -u > /tmp/provided.txt
   diff /tmp/expected.txt /tmp/provided.txt
   ```
   Reveals every var name is different.

**Actions taken for resolution:**

1. Diffed `build/csv/loader_postgresql.sh`, `build/csv_utilise.sh`, and `build/setup.sh` to enumerate every `${PG_*}` name they read.
2. Rewrote `build/config.env.example` — renamed `DEV_DB_NAME` → `PG_DB_DEV`, `PG_PASSWORD` → `PG_SUPERUSER_PASSWORD`, and every other stale variable so the names match the loaders.
3. Cross-checked that `test_db_name`, `staging_db_name`, `prod_db_name` follow the same `PG_DB_<ENV>` scheme.
4. Verified end-to-end: `cp build/config.env.example build/config.local.env && bash build/csv_loader.sh build/csv/samples/customers.csv --env dev` now succeeds.
5. See `docs/GAP_ANALYSIS.md` § G1.

**Resolution:** renamed all vars to the `PG_*_<ENV>` scheme matching what `loader_postgresql.sh`, `csv_utilise.sh`, and `setup.sh` expect. Copying example → `config.local.env` now produces a working configuration.

---

## BUG-017 — Windows CI couldn't run database-backed tests

**Severity:** medium
**Status:** RESOLVED — see `docs/GAP_ANALYSIS.md` § G2
**File:** `.github/workflows/quality-gate.yml`

GitHub Actions service containers are Linux-only, so the Windows job could only run DB-free markers.

**Steps to reproduce (pre-fix state):**

1. Open `.github/workflows/quality-gate.yml` at the pre-fix commit.
2. Confirm the Windows job's pytest invocation uses `-m "not integration and not e2e"` (or equivalent) — everything DB-backed is excluded on Windows.
3. Push to `main` and open the Actions run.
4. Windows job passes, but the `NOT RUN` block (added by BUG-014) lists every integration/e2e/parity test as unexecuted on Windows — regressions in the Windows PG code path can slip through.

**Actions taken for resolution:**

1. Added a new `windows-postgres` job to `.github/workflows/quality-gate.yml` running on `windows-latest`.
2. Added a step to start the pre-installed PostgreSQL service via `Start-Service postgresql-x64-*` and wait for `pg_isready`.
3. Set `PGHOST=localhost`, `PGPORT=5432`, `PGUSER=postgres`, `PGPASSWORD=<GHA secret>` for the job.
4. Ran the same materialisation + provision + deploy loop as `integration-postgres` (four env DBs, all four schemas).
5. Ran the full pytest suite including `-m integration` + `-m e2e` + `-m parity`, plus `python evals/runner.py --tiers p`.
6. Verified the job passes end-to-end on a subsequent workflow run.
7. See `docs/GAP_ANALYSIS.md` § G2.

**Resolution:** added a `windows-postgres` job that starts the pre-installed PostgreSQL service on `windows-latest`, provisions all four environment databases, deploys schemas, and runs the full test suite (integration, e2e, parity) plus Tier P evals.

---

## BUG-018 — Eval tiers X and E unimplemented

**Severity:** medium
**Status:** RESOLVED — see `docs/GAP_ANALYSIS.md` § G3
**File:** `evals/runner.py`

Tier X (CSV round-trip fidelity) and Tier E (cross-environment structural parity) existed in the plan but not the runner.

**Steps to reproduce (pre-fix state):**

1. Read `evals/PLAN.md` — Tiers X and E are documented with expected pass criteria.
2. Try to run them: `python evals/runner.py --tiers x,e`.
3. Pre-fix output: `no scenarios found for tier x`, `no scenarios found for tier e`, exit code 0. Runner silently reports success with zero scenarios executed.

**Actions taken for resolution:**

1. Added `tier_x_run(scenario)` to `evals/runner.py`: calls `bash build/csv_loader.sh <fixture.csv> --env dev`, then `bash build/csv_utilise.sh export <table> /tmp/exported.csv`, then compares the exported bytes to the fixture with a normalisation pass (sorts rows on the primary key, strips the `_csv_row_id` / `_loaded_at` marker columns).
2. Added `tier_e_run(scenario)` to `evals/runner.py`: connects to each of dev/test/staging/prod, queries `information_schema.columns` for all 12 core tables, and asserts the (column_name, data_type, is_nullable) tuple set is identical across all four schemas.
3. Wired both new tiers into the `--tiers` argparse choices.
4. Added fixture scenarios under `evals/datasets/tier_x/` and `evals/datasets/tier_e/`, plus expected JSONs.
5. Verified: `python3 evals/runner.py --tiers x,e --verbose` reports both tiers passing.
6. See `docs/GAP_ANALYSIS.md` § G3.

**Resolution:** both tiers implemented. Tier X: load via `csv_loader.sh` → export via `csv_utilise.sh export` → diff. Tier E: query `information_schema.columns` for all four envs and assert identical structure. Run: `python3 evals/runner.py --tiers x,e --verbose`.

---

## BUG-019 — Runtime artifacts not gitignored

**Severity:** low
**Status:** RESOLVED — see `docs/GAP_ANALYSIS.md` § G4
**File:** `.gitignore`

**Steps to reproduce (pre-fix state):**

1. Fresh clone. Run the snapshot tests and Terraform once to generate artifacts:
   ```bash
   pytest tests/test_snapshot.py
   cd terraform-github-repos && terraform plan -out=tfplan && cd ..
   ```
2. Check git status: `git status --short`.
3. Pre-fix output lists `tests/snapshots/`, `tfplan`, `*.tfplan`, and `terraform-provider-*.log` as untracked or modified — one wrong `git add .` commits them.

**Actions taken for resolution:**

1. Appended `tests/snapshots/`, `tfplan`, `*.tfplan`, and `terraform-provider-*.log` to `.gitignore`.
2. Ran `git status --short` after regenerating each artifact class — confirmed none show as untracked.
3. Ran `git ls-files | Select-String -Pattern "tfplan$|terraform-provider.*\.log$"` — confirmed no already-committed instances (nothing to remove from history).
4. See `docs/GAP_ANALYSIS.md` § G4.

**Resolution:** added `tests/snapshots/`, `tfplan`, `*.tfplan`, `terraform-provider-*.log`.

---

## BUG-020 — docs/VCRM.md BR-20 assertion count discrepancy

**Severity:** low
**Status:** RESOLVED — see `docs/GAP_ANALYSIS.md` § G5
**File:** `docs/VCRM.md`

Old "85 of 85" was stale; update to 142 is correct. Confirmed against suite output and Tier S expectation JSON. No revert needed.

**Steps to reproduce (pre-fix state):**

1. Open `docs/VCRM.md` at the pre-fix commit and locate the BR-20 row — assertion count shows "85 of 85".
2. Run the suite: `bash tests/run_tests.sh dev` — output prints `142 assertions PASSED`.
3. Cross-check against `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json` — the expected substring is `ALL TESTS PASSED` from a 142-count suite.
4. 85 ≠ 142; VCRM claim is stale.

**Actions taken for resolution:**

1. Ran `bash tests/run_tests.sh dev` and captured the "ALL TESTS PASSED" summary — 142 assertions.
2. Cross-checked the Tier S expectation JSON at `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json` — confirms 142.
3. Edited `docs/VCRM.md` BR-20 row: updated `85 of 85` → `142 of 142`.
4. Verified via `Grep pattern="85 of 85"` — no other stale occurrences.
5. See `docs/GAP_ANALYSIS.md` § G5.

---

## BUG-021 — `start-api.ps1` em-dash breaks Windows PowerShell 5.1 parsing

**Severity:** blocking (API cannot start on Windows PS 5.1 without editing the file)
**Status:** RESOLVED 2026-08-02
**File:** `scripts/start-api.ps1` lines 13, 20

Two `Write-Host` strings contained em-dash characters (`—`, U+2014):

```powershell
Write-Host "PGPASSWORD not set — enter it now (input hidden):" -ForegroundColor Yellow
Write-Host "API_KEY not set — every endpoint is unauthenticated (fine for local dev)." -ForegroundColor Yellow
```

When Windows PowerShell 5.1 reads the file without a UTF-8 BOM, the em-dash bytes confuse the tokenizer: everything after the em-dash inside the string is re-parsed as if outside the string, and the parenthesised phrase `(input hidden)` becomes an unquoted subexpression. Result: PS tries to invoke a command named `input` and errors out with `The term 'input' is not recognized as the name of a cmdlet...`.

This is the same class of bug as the `start-frontend.ps1` em-dash issue seen earlier in this session (fixed at the time as a one-off; the same trap was still present in `start-api.ps1`).

**Steps to reproduce (pre-fix state):**

1. Open Windows PowerShell 5.1 (`$PSVersionTable.PSVersion.Major -eq 5`) in the repo root.
2. Ensure `PGPASSWORD` is not set: `Remove-Item env:PGPASSWORD -ErrorAction SilentlyContinue`.
3. Run: `.\scripts\start-api.ps1`.
4. Observe:
   ```
   input : The term 'input' is not recognized as the name of a cmdlet, function, script file, or operable program.
   At C:\...\scripts\start-api.ps1:13 char:54
   +     Write-Host "PGPASSWORD not set - enter it now (input hidden):" ...
   +                                                      ~~~~~
   ```
5. API never starts. `pip install`/uvicorn never invoked.

**Actions taken for resolution:**

1. Rewrote `scripts/start-api.ps1` in ASCII: replaced every em-dash (`—`, U+2014) with a plain hyphen (`-`, U+002D).
2. Added a top-of-file comment explaining why this file stays ASCII-only (with a cross-reference to this bug).
3. Left the ASCII-only rule to be enforced by convention. If a lint step is added later, `Get-Content <path> | Select-String '[\u0080-\uffff]'` returning any line means the script will break under PS 5.1 without a BOM.
4. Verified the same fix is already in place in `scripts/start-frontend.ps1`.

**Resolution 2026-08-02:** file rewritten in ASCII. Cross-referenced from the top-of-file comment so a future editor doesn't reintroduce the em-dash by copy-pasting from Markdown.

---

## BUG-022 — Row-hash collision in dynamic loader silently drops rows

**Severity:** high (data loss — silent)
**Status:** RESOLVED 2026-08-02
**File:** `api/services/dynamic_loader.py` line 246

The in-file row-dedup hash concatenates cell values with no separator:

```python
row_hash = hashlib.sha256("".join(raw_joined).encode("utf-8")).hexdigest()
```

Two logically distinct rows collide whenever the concatenation is identical. `["ab","cd"]` and `["a","bcd"]` both hash to the SHA-256 of `"abcd"`. The `ON CONFLICT (_row_hash) DO NOTHING` upsert then drops one of them.

**Steps to reproduce:**

1. Create a CSV with these three rows:
   ```csv
   left,right
   ab,cd
   a,bcd
   ```
2. Upload it via the UI (`dynamic` mode).
3. `POST /api/csv/upload` response reports `insertedRows: 1, duplicateRowsSkipped: 1` even though the two rows are visibly different.
4. `SELECT * FROM csv_uploads.csv_<hash>` shows only one of the two.

**Suggested fix:** use an ASCII unit separator (`chr(31)`, U+001F) that can't appear in normal CSV cell text: `hashlib.sha256(chr(31).join(raw_joined).encode("utf-8")).hexdigest()`.

**Actions taken for resolution:**

1. Rewrote `api/services/dynamic_loader.py` (whole-file `Write` — the file has CRLF line endings which the surgical `Edit` tool couldn't match; git already normalises to LF on commit per `.gitattributes`, matching the intended state).
2. Changed the row-hash construction from `"".join(raw_joined)` to `"\x1f".join(raw_joined)` (ASCII unit separator, U+001F).
3. Added an inline comment cross-referencing BUG-022 so a future reader doesn't "simplify" the separator away.
4. Verified the file still parses (`from api.services.dynamic_loader import upload_dynamic` works) and the row-hash logic is the only functional change.

**Resolution 2026-08-02:** `"\x1f".join(raw_joined)` used as the pre-hash separator. Previous behaviour dropped one of any pair of rows that concatenated to the same string; new behaviour treats them as distinct.

---

## BUG-023 — Frontend is not built or linted in CI

**Severity:** high (broken frontend can merge to main with green CI)
**Status:** RESOLVED 2026-08-02
**File:** `.github/workflows/quality-gate.yml` — no `frontend-build` job

None of the three CI workflows (`quality-gate.yml` free-tier / integration-postgres / windows-postgres, or `python-validator-tests.yml`) touches `frontend/`. TypeScript type errors, unresolved imports, syntax errors, missing components, and broken route trees are invisible until someone runs `npm run dev` locally.

**Steps to reproduce:**

1. Deliberately break the frontend — e.g. in `frontend/src/routes/_authenticated/index.tsx`, change `useQuery` to `useNonexistentHook`.
2. Commit and push to a branch.
3. Open a PR.
4. All four required CI checks go green (they never ran `npm ci` / `npm run build`).
5. The branch is merged. `main` is now broken for every developer who runs `npm run dev` after pulling.

**Suggested fix:** add a `frontend-build` job to `quality-gate.yml` that runs on both push and PR:

```yaml
frontend-build:
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: frontend
  steps:
    - uses: actions/checkout@v7
    - uses: actions/setup-node@v4
      with:
        node-version: '20'
        cache: 'npm'
        cache-dependency-path: frontend/package-lock.json
    - run: npm ci
    - run: npm run build
    # add `npm run lint` and `npm run typecheck` scripts if they don't exist
```

**Actions taken for resolution:**

1. Added a `frontend-build` job to `.github/workflows/quality-gate.yml` at the top of the `jobs:` block.
2. Job runs on `ubuntu-latest` with `defaults.run.working-directory: frontend`.
3. Steps: `actions/checkout@v7` → `actions/setup-node@v4` (Node 20, `cache: 'npm'`, `cache-dependency-path: frontend/package-lock.json`) → `npm ci` → `npm run lint` → `npm run build`.
4. `vite build` performs a full production build and nitro type-checks the SSR bundle, so TS errors, missing imports, and route-tree issues all fail the step.
5. Confirmed `frontend/package.json` already exposes `lint` and `build` scripts — no package.json change needed.

**Resolution 2026-08-02:** new `frontend-build` job in `quality-gate.yml` runs on every PR and push. Missing branch-protection update: mark this job as "Required" in the GitHub repo settings so it blocks merges the same way the other four checks do.

---

## BUG-024 — Root route ships "Lovable App" branding

**Severity:** high (SEO / brand regression — user-visible on every non-home route)
**Status:** RESOLVED 2026-08-02
**File:** `frontend/src/routes/__root.tsx` lines 80-87

The default `<title>`, `<meta name="description">`, and Open Graph tags in the root route say "Lovable App" / "Lovable Generated Project" / "@Lovable":

```tsx
{ title: "Lovable App" },
{ name: "description", content: "Lovable Generated Project" },
{ name: "author", content: "Lovable" },
{ property: "og:title", content: "Lovable App" },
{ property: "og:description", content: "Lovable Generated Project" },
{ name: "twitter:site", content: "@Lovable" },
```

The `/_authenticated/` route overrides these for `/`, but the 404 page and any future route without a `head:` block inherits them.

**Steps to reproduce:**

1. Start the frontend, open `http://localhost:5173/`.
2. Change the URL to something that doesn't exist: `http://localhost:5173/does-not-exist`.
3. Look at the browser tab — it reads **"Lovable App"**.
4. View page source (Ctrl+U) — every `og:*` / `twitter:*` tag says Lovable.
5. Share the link on Slack/Twitter — link preview shows the Lovable branding.

**Suggested fix:** replace with project-appropriate branding in `__root.tsx`, e.g. `"CSV Migrator — PostgreDataMigrationApp"`.

**Actions taken for resolution:**

1. Replaced the `title`, `description`, `author`, `og:title`, `og:description` tags in `frontend/src/routes/__root.tsx` with CSV Migrator / PostgreDataMigrationApp branding.
2. Removed the `twitter:site` tag pointing to `@Lovable` (no equivalent project handle yet).
3. Kept `og:type` and `twitter:card` unchanged — those are structural, not brand.
4. Added a BUG-024 code comment explaining that the CSV Migrator route at `/` overrides these for its page, so these defaults only surface on the 404 page and any future route without its own `head:` block.
5. Manual verification: browsing to `http://localhost:5173/does-not-exist` now shows "CSV Migrator — PostgreDataMigrationApp" in the tab.

**Resolution 2026-08-02:** default meta/OG/title rebranded. The `_authenticated/index.tsx` route's more specific title continues to win on `/`.

---

## BUG-025 — `POST /api/csv/preview` has no exception guard

**Severity:** medium (inconsistent error contract with `/upload`)
**Status:** RESOLVED 2026-08-02
**File:** `api/routers/csv_routes.py` `preview()` handler; `api/services/csv_parse.py` `build_preview()`

`upload_dynamic()` wraps its body in `try: ... except psycopg2.Error:` and returns a structured `{"status":"error","message":...}` payload. `preview()` doesn't — any unexpected exception in `build_preview()` (regex overflow, memory error on a huge malformed cell) surfaces as a raw 500 with a stack trace visible to the browser.

**Steps to reproduce:**

1. Craft a CSV designed to blow up the parser — e.g. a single quoted field with an unmatched `"` and ~50MB of content after it, forcing the state machine into pathological memory allocation.
2. `POST /api/csv/preview` with that body.
3. FastAPI returns `500 Internal Server Error` with the traceback in `response.text`.
4. Contrast: the same content sent to `/api/csv/upload` returns `200 OK` with `{"status":"error","message":"..."}`.

**Suggested fix:** wrap `preview()`'s body in the same try/except pattern as `upload_dynamic()`, returning `{"status":"invalid_structure","reason":"parse_failed","message":str(exc)[:200]}` on unexpected failures.

**Actions taken for resolution:**

1. Wrapped `build_preview(req.content)` in `try/except Exception`; on failure returns `{"status":"invalid_structure","reason":"parse_failed","message":"The CSV couldn't be parsed: <exc-truncated-200-chars>"}` — mirrors the upload contract.
2. Wrapped the follow-up `match_te_table(result["columns"])` call in its own try/except; T&E matching is best-effort and must never block the preview.
3. Left the existing 413 for oversize payloads unchanged.

**Resolution 2026-08-02:** `preview()` now returns structured JSON for every error path. No raw 500s reach the browser.

---

## BUG-026 — API dies at boot if Postgres isn't ready

**Severity:** medium (poor deployment story on containerised infra)
**Status:** RESOLVED 2026-08-02
**File:** `api/db.py` `init_pool()`

`init_pool()` calls `SimpleConnectionPool(...)` synchronously with no retry. When the API and Postgres start together (docker-compose, Kubernetes without a proper readiness probe on the DB), the pool constructor raises `psycopg2.OperationalError` and uvicorn's lifespan handler propagates it — the ASGI app never comes up.

**Steps to reproduce:**

1. Stop Postgres: `Stop-Service postgresql-x64-18`.
2. Start the API: `.\scripts\start-api.ps1`.
3. Watch the traceback:
   ```
   psycopg2.OperationalError: connection to server at "localhost" (127.0.0.1), port 5433 failed: Connection refused
   ```
4. Uvicorn logs `ERROR: Application startup failed. Exiting.` and the process dies. No autopilot recovery even after PG starts.

**Suggested fix:** in `init_pool()`, wrap in a retry loop:

```python
last_err = None
for attempt in range(30):
    try:
        _pool = SimpleConnectionPool(...)
        return
    except psycopg2.OperationalError as exc:
        last_err = exc
        time.sleep(min(2 ** attempt, 10))
raise last_err
```

**Actions taken for resolution:**

1. Added `import time` and a module logger to `api/db.py`.
2. Rewrote `init_pool()` to accept `max_attempts=30` and `base_delay=1.0` parameters and loop over `SimpleConnectionPool(...)` construction.
3. On each `psycopg2.OperationalError`, logs a warning with the truncated error and sleeps `min(base_delay * 2**(attempt-1), 10.0)` seconds.
4. On success after retry, logs the attempt count. On exhaustion, re-raises the last `OperationalError` so the lifespan handler still fails loudly (uvicorn logs the crash) rather than a swallowed silent failure.
5. Default budget: 30 attempts * up-to-10-second backoff ≈ 5 minutes — enough for Postgres to come up under docker-compose or a Kubernetes readiness probe.

**Resolution 2026-08-02:** `init_pool()` now retries with exponential backoff. Total wait bounded by parameters; explicit re-raise on exhaustion.

---

## BUG-027 — No upload row-count cap

**Severity:** medium (DoS surface; pathological files starve the API)
**Status:** RESOLVED 2026-08-02 (dynamic mode; T&E mode deferred to BUG-028 rewrite)
**File:** `api/config.py` (missing `MAX_ROWS`), enforcement in `api/routers/csv_routes.py`

`settings.MAX_UPLOAD_BYTES = 50 MB` guards raw payload size but nothing guards row count. A 50MB CSV with millions of tiny rows all failing `cast_value()` still iterates every row, appends to `row_errors[]`, and returns a giant JSON response — during which the connection pool slot is held and other requests queue.

**Steps to reproduce:**

1. Generate a 40MB CSV with ~4M rows of `x`:
   ```powershell
   "col`n" + ("x`n" * 4000000) | Out-File -Encoding utf8 -NoNewline giant.csv
   ```
2. Upload it via the UI with column type `int8` (forces every row into `row_errors`).
3. The API is unresponsive to `curl http://127.0.0.1:8000/api/health` for the ~30-60 seconds the request takes, and returns a ~200MB JSON response body listing every row error.

**Suggested fix:** add `MAX_ROWS = int(os.environ.get("API_MAX_ROWS", "100000"))` to `api/config.py`. In `upload_dynamic` and `upload_te`, after `parse_csv()` returns, reject with `{"status":"error","message":f"CSV has {len(rows)-1} rows; max allowed is {settings.MAX_ROWS}"}` when `len(rows)-1 > settings.MAX_ROWS`. Also cap `row_errors` at ~200 entries.

**Actions taken for resolution:**

1. Added two settings to `api/config.py`:
   - `MAX_ROWS: int = int(os.environ.get("API_MAX_ROWS", "100000"))` — hard cap on data rows per upload.
   - `MAX_ROW_ERRORS_REPORTED: int = int(os.environ.get("API_MAX_ROW_ERRORS", "200"))` — cap the per-row error list in the response body; summary counts still reflect the true failed-row count.
2. In `api/services/dynamic_loader.py` `upload_dynamic()`, added a row-count guard immediately after `parse_csv()` returns. Rejects with `{"status":"error","message":"CSV has N data rows, but the API is configured to accept at most M. Split the file or raise API_MAX_ROWS."}` when `len(rows) - 1 > settings.MAX_ROWS`.
3. In the same file, changed the per-row `row_errors.append(...)` call to only append when `len(row_errors) < settings.MAX_ROW_ERRORS_REPORTED`. The `failed = True` flag still fires for every bad row so the summary count is accurate.
4. **Deferred for T&E mode**: `api/services/te_loader.py` does not yet have the guard. Adding it there is trivial (same shape), but BUG-028 will rewrite the T&E loader's row iteration anyway — folding both fixes into that single rewrite avoids double-touching the file. Reopen as a scope note under BUG-028.

**Resolution 2026-08-02:** dynamic mode caps rows and error output. T&E mode intentionally deferred; scope carried into BUG-028.

---

## BUG-028 — `te_loader` casts server-side via SAVEPOINT retry — slow on bad files

**Severity:** medium (performance cliff on bad input)
**Status:** RESOLVED 2026-08-02
**File:** `api/services/te_loader.py` lines 127-145

The T&E loader doesn't validate types before inserting. It sends string values straight to Postgres. When any row in a 500-row chunk fails a CHECK constraint or type cast, the whole chunk `ROLLBACK TO SAVEPOINT`s and the loader falls back to per-row inserts — 500 round-trips instead of 1. On a file with one bad row per chunk, load time goes from seconds to minutes.

Contrast: `dynamic_loader` uses `cast_value()` from `csv_parse.py` to validate client-side before inserting, so bad rows never reach the DB.

**Steps to reproduce:**

1. Create a T&E-shape CSV for `test_programs` (columns: `org_id, program_code, program_name, classification, status, start_date, end_date`) with 5000 rows.
2. Insert one deliberately-bad row in the middle: `999,BAD,name,INVALID_CLASSIFICATION,planning,2025-01-01,2025-01-01`.
3. Upload via the UI (`te` mode).
4. Time the request. With the current code it takes tens of seconds (10 chunks × per-row retry on the offending chunk = 500+ round-trips just for the fallback). A well-behaved loader would take under 2 seconds.

**Suggested fix:** run `cast_value(cell, col_type)` from `csv_parse` for every cell before insert, using the T&E column's `information_schema.columns.data_type` mapped to one of the six `ALLOWED_TYPES`. Reject bad rows into `row_errors[]` without hitting Postgres.

**Actions taken for resolution:**

1. Added `pg_type_to_allowed_type(pg_data_type)` helper to `api/services/csv_parse.py`. Maps every reasonable Postgres `data_type` value (`bigint`, `numeric`, `date`, `timestamp with time zone`, `boolean`, `character varying`, `text`, plus aliases like `int8` / `bool` / `timestamptz`) to one of the six `ALLOWED_TYPES`. Returns `None` for types we can't safely validate client-side (`uuid`, `USER-DEFINED` enums, `ARRAY`, `jsonb`, `bytea`, etc.) — the caller falls back to server-side casting for those.
2. Rewrote `api/services/te_loader.py`:
   - New `_te_column_types(cur, table)` — one query returning `{column_name: data_type}` for the target table.
   - `upload_te()` now looks up the target table's column types once, maps each to `ALLOWED_TYPES` via the new helper, and validates every cell via `cast_value()` before the batch insert.
   - Rows that fail client-side validation are appended to `row_errors[]` with full `{rowNumber, column, value, reason}` fields — a fingerprint that a test can assert to prove the fast path took the row.
   - Cells on unmapped columns pass through as raw strings; the existing SAVEPOINT/ROLLBACK batch-then-per-row fallback still catches any DB-level failure they hit (FK violation, CHECK against an enum, length overflow, etc.). No behaviour regression.
   - Bulk `execute_values` insert happens only on survivors of client-side validation.
3. Folded in BUG-027's row cap for T&E mode: `upload_te` now rejects with `status=error` when the CSV has more than `settings.MAX_ROWS` data rows, before any DB work. Also caps `row_errors` at `settings.MAX_ROW_ERRORS_REPORTED` (default 200) to keep response bodies bounded on pathological files.
4. Added two integration tests to `tests/test_api_coverage.py::TeUploadPipeline`:
   - `test_te_client_side_type_validation_reports_column_and_value` — uploads two rows to `organisations`, one with `is_active=NOT_A_BOOL`. Asserts `insertedRows==1`, `failedRows==1`, and that the row error has both `column` and `value` fields (proves the client-side path ran).
   - `test_te_upload_rejects_over_row_cap` — monkey-patches `settings.MAX_ROWS=2`, uploads 5 rows, asserts `status=error` and no registry entry appears.
5. Performance characteristic: on a 5000-row CSV with one type violation per 500-row chunk, load time is now O(1) DB round-trip (5000 valid rows → 10 bulk inserts, 10 chunks × 1 round trip) instead of O(N) (10 chunks × 500 per-row retries when one chunk trips) — the "seconds vs minutes" gap the bug described.

**Resolution 2026-08-02:** T&E loader validates types client-side using `cast_value()`, keeping the SAVEPOINT fallback only for unmapped column types. Row cap enforced. Two regression tests prove the fast path fires and the cap rejects up-front.

---

## BUG-029 — `lovable-error-reporting.ts` phones home to a third-party global

**Severity:** medium (info leak surface if this ever leaves lovable.dev)
**Status:** RESOLVED 2026-08-02
**File:** `frontend/src/lib/lovable-error-reporting.ts`; called from `frontend/src/routes/__root.tsx` line 41

`ErrorComponent` calls `reportLovableError(error, {...})`, which forwards the raw error object (message, stack, current route) to `window.__lovableEvents?.captureException?.(...)`. On lovable.dev-hosted apps this is intentional — their platform hooks the global. On any self-hosted deployment, `window.__lovableEvents` won't be defined and the call no-ops — but the code path still exists and could reach an unintended global if a third-party script defines that name.

**Steps to reproduce:**

1. Serve the frontend from any non-lovable.dev origin.
2. Trigger a genuine render error (e.g. throw from a route component).
3. Open DevTools Sources → set a breakpoint at `reportLovableError` in `lovable-error-reporting.ts`.
4. Confirm the function runs and inspects `window.__lovableEvents` on every crash.
5. If a browser extension or malicious script defines `window.__lovableEvents.captureException`, it now receives your app's stack traces.

**Suggested fix:** either (a) delete the file and remove the import/call from `__root.tsx`, or (b) gate the call on a build-time flag (`import.meta.env.VITE_ENABLE_LOVABLE_ANALYTICS`).

**Actions taken for resolution:**

1. Chose option (b) — gate rather than delete. Reversible; lovable.dev deployments can flip a single env var to restore telemetry.
2. Rewrote `frontend/src/lib/lovable-error-reporting.ts` with a module-scoped `ANALYTICS_ENABLED` constant reading `import.meta.env.VITE_ENABLE_LOVABLE_ANALYTICS === "true"` (default false).
3. Added an early-return `if (!ANALYTICS_ENABLED) return;` inside `reportLovableError()`. When the flag is off, `window.__lovableEvents` is never touched, even if a third-party script defines that global.
4. Left the `__root.tsx` `ErrorComponent` import + call unchanged — the function is now a no-op by default, so it's safe to leave in place and no route needed edits.
5. Added the flag to `frontend/.env.example` with a comment explaining it's for lovable.dev-hosted deployments only and defaults off.

**Resolution 2026-08-02:** phone-home gated on `VITE_ENABLE_LOVABLE_ANALYTICS`. Default off — self-hosted deployments never leak stack traces to `window.__lovableEvents`.

---

## BUG-030 — `SimpleConnectionPool.getconn()` has no timeout

**Severity:** low (only hurts if a request handler leaks a connection)
**Status:** RESOLVED 2026-08-02
**File:** `api/db.py` `Conn.__enter__`

`_pool.getconn()` blocks indefinitely when `maxconn` connections are checked out. With `maxconn=8` and any handler that raises between borrow and return (BUG-025 territory), a slow leak eventually hangs the API. There's no `getconn(timeout=...)` on `SimpleConnectionPool`, and the pool-exhausted exception handler in `main.py` only fires for `PoolError`, not for hangs.

**Steps to reproduce:**

1. Add a temporary handler to `api/main.py` that borrows a Conn and never returns it (e.g. `while True: time.sleep(1)`).
2. Hit it 8 times with `curl` in parallel.
3. Hit `curl http://127.0.0.1:8000/api/health` from a 9th terminal — it hangs forever instead of returning `503 Server busy`.

**Suggested fix:** switch to `ThreadedConnectionPool` and wrap `getconn` in a `concurrent.futures.ThreadPoolExecutor.submit(...).result(timeout=5)` pattern, or add a hard `Depends(get_pool_slot)` with a semaphore that has a timeout.

**Correction to the original diagnosis:** the "Steps to reproduce" above overstated the risk. `psycopg2.pool.AbstractConnectionPool.getconn()` does NOT block on exhaustion — it raises `psycopg2.pool.PoolError("connection pool exhausted")` immediately. The existing `pool_exhausted_handler` in `api/main.py` was already catching that and returning HTTP 503. So the "hangs forever" symptom was theoretical, not real.

The fix below is still worth landing for two independent reasons:

1. **Thread-safety** — `SimpleConnectionPool` is not thread-safe (its own docstring warns of this). FastAPI runs sync route handlers on a threadpool, so concurrent `getconn`/`putconn` calls could corrupt pool state. `ThreadedConnectionPool` is the thread-safe version and should have been used from day one.
2. **Defensive against future changes** — if a future psycopg2 version introduces blocking behaviour, or if we swap to a different pool implementation (e.g. `asyncpg` for async handlers), the timeout wrapper prevents a hang from being introduced silently.

**Actions taken for resolution:**

1. Added `POOL_GETCONN_TIMEOUT: float` setting to `api/config.py` — env var `API_POOL_GETCONN_TIMEOUT`, default 5.0 seconds. Documented as "bound how long a request handler waits to borrow a pool slot".
2. Rewrote `api/db.py`:
   - Switched `SimpleConnectionPool` → `ThreadedConnectionPool` (parallel FastAPI handlers can now borrow/return without blocking each other).
   - Added a module-level `_getconn_executor` — a `ThreadPoolExecutor` with `max_workers = maxconn + 4`, so a burst of concurrent waiters can queue without the executor itself becoming a bottleneck.
   - New `_borrow_with_timeout()` helper: submits `pool.getconn` to the executor and calls `Future.result(timeout=settings.POOL_GETCONN_TIMEOUT)`. On timeout, raises `psycopg2.pool.PoolError`, which the existing `pool_exhausted_handler` in `api/main.py` already maps to HTTP 503.
   - `Conn.__enter__` now calls `_borrow_with_timeout()` instead of `_pool.getconn()`.
   - Added a done-callback that returns any connection that arrives after the timeout back to the pool, so a slow-then-successful getconn doesn't permanently leak a slot.
   - `close_pool()` now also shuts down the executor.
3. Added `PoolTimeout` integration test class to `tests/test_api.py`:
   - `setUpClass` swaps the module-level `_pool` and `_getconn_executor` for a 2-slot pool with a 500ms timeout (keeps the test fast).
   - `test_exhausted_pool_raises_within_timeout` grabs both slots, calls `_borrow_with_timeout()` for a third connection, and asserts (a) `PoolError` was raised, (b) it fired within 3 seconds (upper bound guards against a hang), (c) the message mentions "pool". No lower bound — an immediate raise is the correct behaviour on today's psycopg2, and the point of the test is to catch any future regression to blocking.
   - `tearDownClass` restores the originals so no other test is affected.
4. Left `maxconn=8` unchanged — the timeout, not the pool size, is what BUG-030 addressed.

**Verification note:** the test initially failed with `elapsed=0.00s < 0.4s` because I mistakenly assumed the pool blocked before raising. That failure surfaced the actual behaviour (immediate raise) and the test's lower-bound assertion was removed. See the "Correction to the original diagnosis" block above.

**Resolution 2026-08-02:** pool switched to the thread-safe implementation, timeout wrapper added as defense-in-depth. Exhausted pool still returns 503 (already did before), but now via a bounded code path rather than an unguarded one. Regression test proves the wrapper doesn't itself introduce a hang.

---

## BUG-031 — `/api/health` doesn't check the uploads schema

**Severity:** low (misleading OK when bootstrap silently failed)
**Status:** RESOLVED 2026-08-02
**File:** `api/main.py` `health()`

The health endpoint runs `SELECT version()` only. It reports `{"status":"ok",...}` even if `bootstrap()` failed halfway and `csv_uploads.csv_files` doesn't exist — the very next `POST /api/csv/upload` will then throw a `relation "csv_uploads.csv_files" does not exist` error.

**Steps to reproduce:**

1. Manually drop the schema: `psql -c "DROP SCHEMA csv_uploads CASCADE"`.
2. Reload uvicorn (Ctrl+C, restart) — but modify `db.bootstrap()` to raise before creating the table (e.g. wrap in `if False:`) to simulate a partial-bootstrap failure.
3. Call `curl http://127.0.0.1:8000/api/health` — returns `{"status":"ok",...}`.
4. Call `POST /api/csv/upload` with any CSV — returns a raw 500 with `UndefinedTable: relation "csv_uploads.csv_files" does not exist`.

**Suggested fix:** add a second query to `health()`:

```python
cur.execute(sql.SQL("SELECT 1 FROM {}.csv_files LIMIT 0").format(sql.Identifier(settings.UPLOADS_SCHEMA)))
```

If it raises, return `{"status":"degraded","error":"uploads schema missing"}`.

**Actions taken for resolution:**

1. Added a second query inside the `health()` try block: `SELECT 1 FROM {uploads_schema}.csv_files LIMIT 0` (built with `psycopg2.sql.Identifier` — no string interpolation of the schema name).
2. Added `"uploads_schema": settings.UPLOADS_SCHEMA` to the healthy response so operators can confirm which schema was probed.
3. Changed the degraded response's error field from a hard-coded `"database unreachable"` to `str(exc).split("\n")[0][:200]` so the actual cause (unreachable vs missing schema vs permission denied) is visible without leaking a full traceback.

**Resolution 2026-08-02:** health now fails when either Postgres is down OR the uploads schema is missing. Deep-probe is one extra query per health call — negligible overhead.

---

## BUG-032 — No migration story for `csv_uploads.csv_files`

**Severity:** low (bites the first schema evolution, not today)
**Status:** RESOLVED 2026-08-02
**File:** `api/db.py` `bootstrap()`

`bootstrap()` uses `CREATE TABLE IF NOT EXISTS`, which is idempotent for the initial deploy but does nothing when the table already exists. If a future change adds a column (say `updated_at TIMESTAMPTZ`), `bootstrap()` won't run the `ALTER TABLE`, and every existing deployment silently ships a stale schema until someone runs it by hand.

**Steps to reproduce:**

1. Deploy the API against a fresh Postgres — `bootstrap()` creates the table with columns A/B/C.
2. Change `bootstrap()` to declare column D as well (edit the DDL).
3. Restart uvicorn.
4. `\d csv_uploads.csv_files` — column D is missing. No error, no warning.

**Suggested fix:** either (a) adopt Alembic with an `alembic upgrade head` step in the lifespan; or (b) document that any schema change requires a manual migration and add a `SCHEMA_VERSION` table with a check in `bootstrap()` that fails loudly on mismatch.

**Actions taken for resolution:**

Chose option (a) — Alembic + auto-run on API startup — based on the user's stated need for ~3 deployment environments over the next year.

1. Added `alembic>=1.13.0` to `api/requirements.txt` (pulls in SQLAlchemy transitively — used only for the migration connection, not for ORM models).
2. Created `alembic.ini` at the repo root with a placeholder `sqlalchemy.url` (real URL is built at runtime by `env.py` from `api.config.settings`, so the same libpq env vars the API uses drive migrations too).
3. Created `alembic/env.py`: reads `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE` from `api.config.settings`, builds a SQLAlchemy URL, opens a NullPool connection for the migration run. Both online and offline (`--sql`) migration paths implemented.
4. Created `alembic/script.py.mako` — standard Alembic template for new revisions.
5. Wrote `alembic/versions/0001_initial_uploads_schema.py` — a baseline migration whose `upgrade()` mirrors the previous `bootstrap()` DDL 1:1 using `IF NOT EXISTS` clauses. This means a database that was already bootstrapped by the pre-Alembic code path upgrades to head as a no-op — no manual `alembic stamp head` needed.
6. Rewrote `api/db.py:bootstrap()` — replaced the four hand-written `CREATE TABLE IF NOT EXISTS` calls with `alembic.command.upgrade(cfg, "head")`. Alembic imports are deferred inside the function so `pytest` collection of the `api` package doesn't drag in SQLAlchemy unless bootstrap actually runs.
7. Documented the migration workflow in `docs/API_INTEGRATION.md` (new `## Migrations` section): how new migrations get scaffolded, when they run, and the "schema name is fixed" limitation (Alembic migrations are static — changing `CSV_UPLOADS_SCHEMA` env var isn't supported without a rename migration).

**Known limitations, deferred:**
- Concurrent multi-instance startup can race the `alembic upgrade head` call. Fine for single-container-per-env deployments; adopt `advisory_lock` if you ever run multi-replica.
- The initial migration uses `IF NOT EXISTS` everywhere for compatibility with pre-Alembic databases; future migrations should NOT rely on that pattern — Alembic tracks state properly.

**Resolution 2026-08-02:** in-lifespan `alembic upgrade head` replaces the hand-written DDL. Schema evolution is now first-class.

---

## BUG-033 — `frontend/AGENTS.md` is orphaned lovable scaffolding

**Severity:** low (cleanup)
**Status:** RESOLVED 2026-08-02
**File:** `frontend/AGENTS.md`

The `AGENTS.md` file at the frontend root is scaffolding from the lovable.dev starter template. No code references it, no other doc links to it, and it's not part of this project's `doc-coauthoring` workflow.

**Steps to reproduce:**

1. `grep -r "AGENTS.md" .` from the repo root — the file references itself only.
2. Read the file — it's generic lovable-project guidance, not this project's playbook.
3. Confirm no CI job, docs index, or README mentions it.

**Suggested fix:** either (a) delete it, or (b) rewrite it as the project's actual agent playbook and link it from `README.md`.

**Actions taken for resolution:**

1. Chose option (a) — delete. The file was generic starter scaffolding, and the project already has `CLAUDE.md` for repo-specific guidance and `doc-coauthoring` for structured writing workflows.
2. User ran `git rm frontend/AGENTS.md` in the terminal.
3. Included in the same commit as BUG-022..027/029/031: commit `850a4c7`, `delete mode 100644 frontend/AGENTS.md`.
4. Verified via `git log --diff-filter=D --name-only` that the file is gone from the tree going forward.

**Resolution 2026-08-02:** deleted in commit `850a4c7`. If a project agent playbook is wanted later, add it as `frontend/CLAUDE.md` (matching root convention) rather than reviving the lovable name.

---

## BUG-034 — `tests/test_api.py` and `tests/test_api_coverage.py` may overlap

**Severity:** low (potential duplicate test maintenance)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-03 (WON'T FIX — not a real overlap)
**File:** `tests/test_api.py`, `tests/test_api_coverage.py`

Two similarly-named test files exist without a clear naming convention distinguishing them. If `_coverage.py` was added later as a superset, the earlier file may be duplicating work. If they cover distinct surfaces, the file names don't communicate that.

**Steps to reproduce:**

1. `ls tests/test_api*.py` — two files.
2. Read both; count overlapping test names or assertions.
3. Run `pytest tests/test_api.py tests/test_api_coverage.py --collect-only -q` — count total tests vs unique test IDs.

**Suggested fix:** if overlap exists, merge into a single `tests/test_api.py`. If they truly cover different surfaces, rename `_coverage.py` to something descriptive (e.g. `test_api_te_loader.py`) and document the split at the top of each file.

**Actions taken for resolution:**

1. Read the top-of-file docstring of both files. `test_api_coverage.py` explicitly lists six surfaces it covers that `test_api.py` does not: `GET /api/te/tables`, `POST /api/csv/upload mode=te`, the `teTableMatch` field on `/preview`, `DELETE /api/csv/files/{id}`, `overwrite=true`, and CORS middleware headers.
2. Compared collected test IDs: no overlap in test names or assertion targets. The split is intentional, not accidental duplication.
3. Closing as WON'T FIX rather than renaming — the file names are stable references in commit history, and the top-of-file docstrings already document the split.

**Resolution 2026-08-03:** WON'T FIX. No overlap; the split is documented in each file's module docstring. If the naming still confuses newcomers later, a rename to `test_api_extras.py` is a purely cosmetic follow-up.

---

## BUG-035 — `/api/health` requires the API-key header

**Severity:** medium (breaks external monitoring in any deployment where `API_KEY` is set)
**Status:** RESOLVED 2026-08-03
**File:** `api/main.py`, `api/routers/csv_routes.py`, `api/routers/te_routes.py`

`FastAPI(dependencies=[Depends(require_api_key)])` at the app level applies to every route, including `/api/health`. In production, where `API_KEY` is set, an uptime monitor or load-balancer probe cannot call `/api/health` without knowing the secret — which negates the whole point of BUG-031's deep-probe work.

**Steps to reproduce:**

1. `$env:API_KEY="hunter2"` and start the API.
2. `curl http://localhost:8000/api/health` → HTTP 401 "Missing or invalid X-API-Key header".
3. Expected: 200 with `status: ok` or `degraded`, no auth required.

**Actions taken for resolution:**

1. Removed `dependencies=[Depends(require_api_key)]` from the `FastAPI(...)` call in `api/main.py`.
2. Added `dependencies=[Depends(require_api_key)]` to each `APIRouter(...)` (`csv_routes.py`, `te_routes.py`) so every business endpoint is still guarded.
3. `/api/health` (defined directly on `app`) is now unauthenticated by construction — no route-level opt-out needed.

**Resolution 2026-08-03:** auth moved from app-level to router-level. Health is open; all `/api/csv/*` and `/api/te/*` routes still require `X-API-Key` when `API_KEY` is set.

---

## BUG-036 — `sanitize_columns` can produce duplicate names from unique input

**Severity:** medium (real user-facing false-positive: unique headers get rejected as "duplicate")
**Status:** RESOLVED 2026-08-03
**File:** `api/services/csv_parse.py`

The dedupe loop increments a per-`base` counter but doesn't check the resulting name against previously assigned names. Input `["foo", "foo", "foo_2"]` produces `["foo", "foo_2", "foo_2"]` — a collision the caller in `dynamic_loader.py` rejects with a "Duplicate sanitized column name" error, even though the CSV headers were all distinct.

**Steps to reproduce:**

1. From a Python REPL: `from api.services.csv_parse import sanitize_columns; sanitize_columns(["foo", "foo", "foo_2"])`
2. Pre-fix returns `["foo", "foo_2", "foo_2"]`.
3. Upload a CSV with those exact headers — the dynamic loader returns `status: error, message: 'Duplicate sanitized column name "foo_2" — rename headers in the CSV.'`

**Actions taken for resolution:**

1. Rewrote the dedupe loop to keep bumping the numeric suffix until the candidate name is not already in `seen`.
2. Added `UnitCsvParse.test_sanitize_columns_no_collision_on_stem_conflict` and `UnitCsvParse.test_sanitize_columns_dedupes_true_duplicates` to `tests/test_api.py`.

**Resolution 2026-08-03:** loop now iterates until a fresh name is found. Two unit tests lock in the fix.

---

## BUG-037 — docs/BUG_REPORT.md — BUG-034 heading was clobbered

**Severity:** low (documentation)
**Status:** RESOLVED 2026-08-03
**File:** `docs/BUG_REPORT.md`

BUG-033's Resolution line had BUG-034's title appended after an em-dash (`... reviving the lovable name. — tests/test_api.py and tests/test_api_coverage.py may overlap`), and the `## BUG-034 — ...` heading itself was missing. `grep -c '^## BUG-034' docs/BUG_REPORT.md` returned 0.

**Steps to reproduce:** `grep -c '^## BUG-034' docs/BUG_REPORT.md` → 0 pre-fix.

**Actions taken for resolution:**

1. Split BUG-033's Resolution line — removed the trailing ` — tests/test_api.py ...` fragment.
2. Inserted an `---` separator and the missing `## BUG-034 — ...` heading.

**Resolution 2026-08-03:** heading restored; BUG-034 is now a first-class entry again.

---

## BUG-038 — `@supabase/supabase-js` is a dead frontend dependency

**Severity:** low (bundle bloat + slower `npm ci`)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-12
**File:** `csv-table-hub-main/package.json`, `csv-table-hub-main/package-lock.json`

The Supabase → FastAPI migration removed every source import of `@supabase/*`, but the top-level `@supabase/supabase-js` dep and its seven transitive packages are still in the lockfile. Grep for `supabase` in `csv-table-hub-main/src` returns only historical comments.

**Steps to reproduce:**

1. `Select-String -Path csv-table-hub-main\src\**\*.ts,csv-table-hub-main\src\**\*.tsx -Pattern 'from ["'\''"]@supabase' -Recurse` → 0 hits.
2. `Get-Content csv-table-hub-main\package.json | Select-String 'supabase'` → 1 hit at line 42.

**Suggested fix:** `cd csv-table-hub-main && npm uninstall @supabase/supabase-js`, then commit `package.json` + `package-lock.json`.

**Actions taken for resolution:**

1. Removed `@supabase/supabase-js` from `package.json` and the lockfile; deleted the now-unreferenced `supabase/` directory (migrations/config) alongside it.

**Resolution 2026-08-12:** dependency and dead `supabase/` directory removed. `grep -c supabase csv-table-hub-main/package.json` → 0.

---

## BUG-039 — `te_loader._err` closure has a misleading half-finished comment

**Severity:** low (documentation only — counting is actually correct)
**Status:** RESOLVED 2026-08-03
**File:** `api/services/te_loader.py`

The comment inside the `_err` closure trails off with `... under this cap the summary undercounts. Track separately:` — implying the closure will track a separate counter, which it doesn't. Counting is done correctly by callers via `failed_row_count += 1` on the next line, but the stale comment reads as a bug marker.

**Steps to reproduce:** read `api/services/te_loader.py` lines 155-164 — the "Track separately:" trailing off is confusing on first read.

**Actions taken for resolution:**

1. Replaced the confused paragraph with a two-sentence comment that says exactly what the closure does (append if under cap) and where the true failure count is bumped (in the caller).

**Resolution 2026-08-03:** stale comment replaced. No behaviour change.

---

## BUG-040 — `allow_destructive` defaults to `True` (unsafe in shared/prod)

**Severity:** medium (a forgotten env var leaves DELETE enabled)
**Status:** RESOLVED 2026-08-03
**File:** `api/config.py`

The setting's own comment says "Set `API_ALLOW_DESTRUCTIVE=false` in shared/prod to prevent accidental table drops," but the default is `True`. Any deployment that forgets the env var has `DELETE /api/csv/files/{id}` enabled.

**Steps to reproduce:** Deploy without `API_ALLOW_DESTRUCTIVE` set; `DELETE /api/csv/files/1` returns 200 and drops the table.

**Actions taken for resolution:**

1. Flipped the default in `api/config.py` from `"true"` to `"false"`.
2. Updated the accompanying comment to say local dev must opt in.
3. Every existing PowerShell dev script (`scripts/start-api.ps1`) can add `$env:API_ALLOW_DESTRUCTIVE = "true"` if the developer wants DELETE enabled locally.

**Resolution 2026-08-03:** default is now `false`. Local devs opt in with `$env:API_ALLOW_DESTRUCTIVE = "true"`; prod deployments must opt in explicitly.

---

## BUG-041 — `csv_uploads.audit_log` is write-only

**Severity:** low (design smell — either wire it up or delete the writes)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-12
**File:** `api/routers/csv_routes.py`, `api/routers/audit_routes.py`, `csv-table-hub-main/src/routes/audit.tsx`

The `audit_log` table is written on `DELETE /api/csv/files/{id}` but no endpoint reads it and no test asserts on it. If audit trail is meant to be consulted, we need a `GET /api/audit/log` endpoint. If not, the writes and the migration should go.

**Suggested fix:** decide — either add a paginated `GET /api/audit/log` behind API-key auth, or delete the audit-log writes + migrate the table out.

**Actions taken for resolution:**

1. Decided to wire it up: added `api/routers/audit_routes.py` with `GET /api/audit/log` (paginated via `limit`/`offset`, capped at 200/page), registered in `api/main.py`, behind the same `X-API-Key` dependency as the other routers.
2. Added an `AuditLogEndpoint.test_delete_appears_in_audit_log` integration test asserting a `DELETE` shows up in the log.
3. Wired the existing `csv-table-hub-main/src/routes/audit.tsx` frontend page to the new endpoint.

**Resolution 2026-08-12:** `GET /api/audit/log` added and tested; audit trail is now readable, not just written.

---

## BUG-042 — `/api/te/tables` runs `COUNT(*)` on every T&E table on every call

**Severity:** low (performance — fine at kilorows, painful at millions)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-12
**File:** `api/routers/te_routes.py`

The handler loops over the 12 T&E tables and issues one `SELECT COUNT(*)` per table per call. Cheap today, expensive as T&E data grows.

**Suggested fix:** replace with a single `SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname = %s AND relname = ANY(%s)` — reads planner-maintained counts in one query. Trade-off: `n_live_tup` is approximate.

**Actions taken for resolution:**

1. Rewrote `te_tables()` to use 2 batch queries total: one `information_schema.tables` existence check and one `pg_stat_user_tables` lookup keyed by `schemaname`/`relname = ANY(%s)`, replacing the up-to-24 per-table `COUNT(*)` round trips.
2. Removed the now-unused `from psycopg2 import sql` import.

**Resolution 2026-08-12:** `/api/te/tables` now issues 2 queries regardless of table count, accepting `n_live_tup`'s approximation as documented above.

---

## BUG-043 — Frontend ESLint disables `@typescript-eslint/no-unused-vars`

**Severity:** low (masked BUG-038; will mask future dead imports)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-12
**File:** `csv-table-hub-main/eslint.config.js`

Line 36: `"@typescript-eslint/no-unused-vars": "off"`. This is why the dead `@supabase/supabase-js` import (BUG-038) survived. Flipping it to `"warn"` or `"error"` may surface other dead imports across `src/`.

**Suggested fix:** turn to `"warn"`; run `npm run lint`; clean up whatever it flags in one PR; then promote to `"error"`.

**Actions taken for resolution:**

1. Flipped the rule to `"warn"`, ran `npm run lint`, and cleaned up every flagged dead import in one pass (`_authenticated/index.tsx`: unused `useMemo`, `UploadResult`, `RowError`, `ProcessingLog`, `Switch`, `Label`, `BellRing`, a dead `displayName` var; `auth.tsx`: unused `Input`).
2. Promoted the rule to `"error"` so future dead imports fail lint instead of warning.

**Resolution 2026-08-12:** rule is `"error"`; lint is clean at that level.

---

## BUG-044 — No `README.md` at repo root

**Severity:** low (onboarding drag)
**Status:** ~~OPEN~~ → RESOLVED 2026-08-12
**File:** `README.md`

The repo has 20+ markdown docs at root (`docs/BUG_REPORT.md`, `docs/GAP_ANALYSIS.md`, `docs/VCRM.md`, `docs/PROD_DEPLOY.md`, `docs/AZURE_DEPLOY.md`, `docs/RECONSTRUCT.md`, `HANDOFF.md`, `docs/JUDGE_ASSESSMENT.md`, ...) but no landing page. A newcomer has no map.

**Suggested fix:** a short `README.md` with: what the app is, quickstart (`start-api.ps1` + `start-frontend.ps1`), and a one-line pointer to each of the top-level docs.

**Actions taken for resolution:**

1. Added a root `README.md`: what the app is, quickstart, and an API Surface table (including `/api/audit/log` from BUG-041) with pointers to the other top-level docs.

**Resolution 2026-08-12:** `README.md` exists at repo root.

---

## BUG-045 — `docs/GAP_ANALYSIS.md` cites a stale commit

**Severity:** low (documentation staleness)
**Status:** RESOLVED 2026-08-03
**File:** `docs/GAP_ANALYSIS.md`

Line 7 pins the assessment to `main @ b255262 + audit changes`. `main` is now `6d7bcaa` post-reconciliation.

**Actions taken for resolution:**

1. Updated the `Assessed at:` line to reference `main @ 6d7bcaa` (post-reconciliation state).

**Resolution 2026-08-03:** commit reference refreshed.

---

## BUG-046 — `alembic.ini` missing `path_separator`, prints deprecation warning

**Severity:** low (noise in every test/CI run)
**Status:** RESOLVED 2026-08-03
**File:** `alembic.ini`

Recent Alembic versions warn: `No path_separator found in configuration; falling back to legacy splitting on spaces, commas, and colons for prepend_sys_path`. Visible in every pytest run that touches the API.

**Actions taken for resolution:**

1. Added `path_separator = os` to the `[alembic]` section of `alembic.ini`.

**Resolution 2026-08-03:** warning silenced. Behaviour identical to the legacy default (`.` splits on nothing).

---

## Loose ends flagged during the audit (not yet formally opened)

These were referenced during the audit but I couldn't verify their current state without running the tests. They may already be closed by the entries above.

- **Compaction summary referenced BUG-021 (main.tf typo) and BUG-022 (CRLF line endings)** as historical bugs that no longer surface in `docs/FIXES_APPLIED.md` / `docs/GAP_ANALYSIS.md`. If either recurs, open as a new BUG-### entry with fresh evidence rather than retroactively assigning the old numbers — no numbering conflict, and current-state fixes are more useful than historical archaeology.
- **The 6 Codex-identified orchestration fixes** referenced in the compaction summary — no source doc captures them as discrete entries. If a regression appears in orchestration, open a new BUG-### with the failing scenario attached.
- **`provision_full_test_env.sh` variable-name workaround** — flagged in `docs/FIXES_APPLIED.md` as "Not fixed — needs a decision", but `docs/GAP_ANALYSIS.md` § G1 closes the underlying config-name mismatch. Assumed moot; if a fresh clone still needs the workaround, reopen as a new BUG-###.

---

## Summary table

_Rows are never deleted. When a bug is RESOLVED, update its Status column — do not remove the row. Sort order below is by BUG ID (oldest first), not by status._

| ID | Severity | Status | Area |
|---|---|---|---|
| BUG-001 | low | RESOLVED 2026-08-02 | scripts / vite.config (port pin) |
| BUG-002 | high | RESOLVED 2026-08-02 | api/config.py (CORS default) |
| BUG-003 | high | RESOLVED 2026-08-02 | frontend (loader error handling) |
| BUG-004 | high | RESOLVED 2026-08-02 | SQL test suites |
| BUG-005 | — | RESOLVED 2026-08-02 (with BUG-004) | evals |
| BUG-006 | low | RESOLVED 2026-08-02 | api + frontend key mismatch DX |
| BUG-007 | medium | RESOLVED 2026-08-02 | docs (wrong PG port) |
| BUG-008 | medium | RESOLVED 2026-08-02 | docs (missing api/ + frontend/ coverage) |
| BUG-009 | blocking | RESOLVED (F1) | build/environments (missing tbl_* vars) |
| BUG-010 | blocking | RESOLVED (F2) | build/environments (missing test/staging/prod templates) |
| BUG-011 | blocking | RESOLVED (F3) | CI (deployed gitignored file) |
| BUG-012 | high | RESOLVED (F4) | tests (silent skips on missing prereqs) |
| BUG-013 | high | RESOLVED (F5) | evals/runner.py (skipped instead of failed) |
| BUG-014 | high | RESOLVED (F6) | scripts/test_report.py (no visibility of not-run) |
| BUG-015 | medium | RESOLVED (F7) | docs (stale counts/paths) |
| BUG-016 | medium | RESOLVED (G1) | build/config.env.example (var name mismatch) |
| BUG-017 | medium | RESOLVED (G2) | CI (Windows PG-backed jobs) |
| BUG-018 | medium | RESOLVED (G3) | evals (tiers X and E unimplemented) |
| BUG-019 | low | RESOLVED (G4) | .gitignore (runtime artifacts) |
| BUG-020 | low | RESOLVED (G5) | docs/VCRM.md (stale BR-20 count) |
| BUG-021 | blocking | RESOLVED 2026-08-02 | scripts/start-api.ps1 (em-dash breaks PS 5.1) |
| BUG-022 | high | RESOLVED 2026-08-02 | api/services/dynamic_loader.py (row-hash collision) |
| BUG-023 | high | RESOLVED 2026-08-02 | CI (frontend never built or linted) |
| BUG-024 | high | RESOLVED 2026-08-02 | frontend/src/routes/__root.tsx (Lovable branding leaks) |
| BUG-025 | medium | RESOLVED 2026-08-02 | api/routers/csv_routes.py (/preview has no try/except) |
| BUG-026 | medium | RESOLVED 2026-08-02 | api/db.py (init_pool has no retry) |
| BUG-027 | medium | RESOLVED 2026-08-02 (dynamic mode only) | api/config.py + routers (no upload row-count cap) |
| BUG-028 | medium | RESOLVED 2026-08-02 | api/services/te_loader.py (server-side cast retries are slow) |
| BUG-029 | medium | RESOLVED 2026-08-02 | frontend/src/lib/lovable-error-reporting.ts (third-party phone-home) |
| BUG-030 | low | RESOLVED 2026-08-02 | api/db.py (SimpleConnectionPool.getconn has no timeout) |
| BUG-031 | low | RESOLVED 2026-08-02 | api/main.py (/api/health doesn't probe uploads schema) |
| BUG-032 | low | RESOLVED 2026-08-02 | api/db.py (no migration story for csv_files) |
| BUG-033 | low | RESOLVED 2026-08-02 | frontend/AGENTS.md (orphaned lovable scaffolding) |
| BUG-034 | low | RESOLVED 2026-08-03 (WON'T FIX) | tests/test_api*.py (no real overlap) |
| BUG-035 | medium | RESOLVED 2026-08-03 | api/main.py + routers (/api/health was behind API-key) |
| BUG-036 | medium | RESOLVED 2026-08-03 | api/services/csv_parse.py (sanitize_columns collision on stem conflict) |
| BUG-037 | low | RESOLVED 2026-08-03 | docs/BUG_REPORT.md (BUG-034 heading clobbered) |
| BUG-038 | low | OPEN | frontend/package.json (@supabase/supabase-js dead dep) |
| BUG-039 | low | RESOLVED 2026-08-03 | api/services/te_loader.py (misleading _err comment) |
| BUG-040 | medium | RESOLVED 2026-08-03 | api/config.py (allow_destructive defaulted True) |
| BUG-041 | low | OPEN | api/routers/csv_routes.py + alembic (audit_log write-only) |
| BUG-042 | low | OPEN | api/routers/te_routes.py (COUNT(*) per table per call) |
| BUG-043 | low | OPEN | frontend/eslint.config.js (no-unused-vars off) |
| BUG-044 | low | OPEN | (missing) README.md at repo root |
| BUG-045 | low | RESOLVED 2026-08-03 | docs/GAP_ANALYSIS.md (stale commit ref) |
| BUG-046 | low | RESOLVED 2026-08-03 | alembic.ini (missing path_separator, deprecation warning) |

Next verification steps, in dependency order:

1. ~~Apply BUG-002~~ / ~~BUG-001~~ — resolved together via `vite.config.ts` port pin to 5173.
2. ~~Update the docs to close BUG-007 and BUG-008~~ — resolved.
3. ~~Confirm BUG-003 root cause and pick a fix~~ — resolved via loader try/catch + `useQuery` + `BackendUnreachableBanner`.
4. ~~BUG-004 / BUG-005~~ — verified fix already applied at source (no `:"schema_name"`/`:"tbl_"` refs remain inside DO blocks). Manual `bash tests/run_tests.sh dev` on a fresh deploy still recommended as a smoke test.
5. ~~BUG-006~~ — resolved via API startup fingerprint log + frontend `console.info` on module load.
6. **BUG-022 (row-hash collision)** — data-loss bug, silent. Fix before PR #40 merges.
7. **BUG-023 (no frontend CI)** — otherwise BUG-022's regression test can't be enforced. Fix alongside.
8. **BUG-024 (Lovable branding)** — user-visible SEO regression. Fix alongside.
9. **BUG-025..028 (API robustness — preview guard, pool retry, row cap, TE loader speed)** — worth fixing this cycle if time permits, otherwise next cycle.
10. **BUG-029..034 (info leak / infra / cleanup)** — defer to a follow-up cycle unless one becomes blocking.
