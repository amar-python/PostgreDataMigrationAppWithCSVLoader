# Decision: Plan for moving the frontend from React to Streamlit (#212)

Status:  Accepted by the owner on 24 Nov; no question is left open. Steps 1 to 4 were built on the defaults, and the owner confirmed every one of them (see "Owner decisions")
Date:    2026-11-16, updated 2026-11-19
Review:  Before step 5 (packaging) starts. It still needs the offline dry run (#60); the bundle size and the Azure host are decided. The upload spike (step 4) is done and did not change the plan

## Where it stands (19 Nov)

| Step | Issue | State |
|---|---|---|
| 1 App shell | #251 | Merged (#264) |
| 4 Upload spike | #254 | Merged (#265). Outcome "limiting, with workarounds": nothing found made Streamlit wrong for the screen, so the whole-app cutover stands |
| 2 Review screen | #252 | Merged (#267) |
| 3 Import history | #253 | Merged (#269) |
| 4 Upload and imported files | #255 | Merged (#270, with this update) |
| 5 Packaging | #256 | Repository side in a draft PR (24 Nov): the Ubuntu bundle ships Streamlit beside React (`te-streamlit`, port 8501, an eighth PASS line), and `infra/terraform-prod` defines the API and Streamlit apps (`terraform validate` only, nothing applied). Still to do: the clean-VM dry run (#60) with the no-outside-connection check, and on Azure the WebSocket and 50 MiB upload checks |
| 6 Cutover and deletion | #257 | Not started. Needs steps 1 to 5. The accessibility job already scans the Streamlit app too (#388), so the React scans can go with React |
| Tests | #258 | Done as each screen landed: 364 unit tests (`AppTest` and plain functions) and 49 browser tests in four files. The browser tests run in CI in their own `browser` job (#273), a required check on `main` since 24 Nov |

The three screen PRs were stacked and merged in that order on 19 Nov (#267, #269, #270), as merge commits, once each had passed CI. The issues #252, #253 and #255 were closed on 19 Nov on the owner's instruction, each with its evidence in a comment. #253 and #255 were closed with their owner decisions (the audit-log screen and the changelog, the mapping templates) on the plan's defaults, which the owner confirmed on 24 Nov (see "Owner decisions"). #268 was one PR carrying all three screens; it was closed in favour of the stack, and its branch `claude/streamlit-migration-plan` is kept for reference only. The owner accepted the plan on 24 Nov and answered every question under "Owner decisions".

## Choice

Build the Streamlit app as a whole, screen by screen, and **switch over once, not screen by screen**. Keep the React app running for one release as the rollback, then delete it.

| Step | What | Replaces (React lines, non-test) |
|---|---|---|
| 1 | App shell: sign-in, session expiry, role gating, sign-out that clears state, change password | `auth.tsx` 100, `session.ts` 128, `change-password.tsx` 121, `session-menu.tsx` 31, `__root.tsx` 126 |
| 2 | Review screen: productionise the #154 spike | `review-table.tsx` 356, `review.$uploadId.tsx` 33 |
| 3 | Import-history screen, read from the server (not the server's audit log: see "Corrections") | `audit.tsx` 254, `audit-log.ts` 35, the audit parts of `export.ts` |
| 4 | Spike the upload screen (done), then build it, with the imported-files list | `_authenticated/index.tsx` 810, `csv-preview.ts` 165, `job-outcome.ts` 168, `export.ts` 271, `mapping-templates.ts` 73, `use-local-storage.ts` 46 |
| 5 | Package it for the offline bundle and Azure; switch the default URL | `csv.functions.ts` 372 (the API client) goes last |
| 6 | One release later, delete `csv-table-hub-main/` | all of the above, about 3,300 lines and 20 test files, and the accessibility CI job (#168), which scans the React dev server and needs a replacement or a deliberate retirement |

Why this order: the shell is needed by every page, so it comes first; review is already spiked; the import-history screen is read-only and low risk, though it changes where the history comes from; upload is the largest and least proven screen, so it got its own spike before anything was committed to.

## The nine questions from #212

**1. Order.** As above.

**2. Cutover: whole app, not per screen.** The React app keeps its session token in `sessionStorage` on its own origin; Streamlit keeps it in `st.session_state` on another. Running both per screen would make users sign in twice. Both talk to the same API, so there is no data migration, and rolling back is pointing the URL back at React.

**3. Auth and sessions.** The React app has local sign-in only (it has no OIDC code, though the API does: `/api/auth/oidc`). So parity needs only `/api/auth/login`. If OIDC in the UI is wanted later, Streamlit 1.67 can do it: `st.login()` with `expose_tokens = "id"` in `secrets.toml` gives `st.user.tokens["id"]`, which is what `/api/auth/oidc` takes. It needs the `streamlit[auth]` extra (7 more packages). Built in step 1: the session is cleared on a 401 and checked against `expiresAt`; a session the server ended in the middle of an upload signs the person out with a reason.

**4. Offline install (#60).** Measured with the same `pip download` flags `scripts/offline/build_bundle.sh` uses (CPython 3.12, manylinux x86_64, binary wheels only):

| Wheel set | Wheels | Size |
|---|---|---|
| API today (`api/requirements.txt`) | 30 | 25 MB |
| `streamlit` | 34 | 117 MB |
| `streamlit[auth]` | 41 | 123 MB |

Only 10 packages overlap with the API's set, and they are small (0.9 MB), so the bundle (143 MB today) grows by **about 116 MB, to roughly 260 MB**, less whatever the Node runtime and the prebuilt frontend take out (not measured). `openpyxl` (the XLSX reports, added in step 3) is a small pure-Python wheel and was not added to these figures. Every package is a binary wheel and `pip install --no-index --find-links` resolves the whole set offline (checked with `--dry-run`). `install.sh` swaps the `te-frontend` unit for a `te-streamlit` unit, and the API address becomes an environment variable, so the `__OFFLINE_API_BASE__` rewrite goes away. Telemetry defaults to **on** (`gatherUsageStats = true`) and is switched off with `browser.gatherUsageStats = false`; **that it then makes no outside connection was not tested** and must be, on the dry-run VM. Sequence: do the #60 dry run on the current React bundle first, since it stands alone and is overdue; change packaging afterwards, not at the same time. The #60 issue was closed by the owner on 18 Nov, but no dry-run result is recorded in the repository and the README still lists the dry run as to do (BR-37 stays partial until it is done), so this sequencing still stands.

**5. Deployment.** On-premises it is one more systemd unit, like `te-frontend` now. In Azure, `infra/terraform-prod`, the Dockerfile and the entrypoint define no frontend at all today, so Streamlit adds a service there rather than replacing one, and the owner needs to say where it should run. Anything in front of Streamlit must pass WebSockets through; this was not tested.

**6. Upload and preview screen: spiked, then built.** The spike (#254, `e2e/test_streamlit_upload_spike.py`, 11 tests) answered its seven questions against the real API. What the production screen (#255) did with each:

| Question | Spike answer | What the screen does |
|---|---|---|
| Size limit | Cannot be one setting: Streamlit counts a megabyte as 1,000,000 bytes, the API 50 MiB | `server.maxUploadSize = 53` in `config.toml`; the app checks the real limit from `MAX_UPLOAD_BYTES` and refuses in its own words, before anything is sent |
| Column mapping | `st.data_editor` works, but its grid is a canvas | Ordinary widgets: a text box and a type select per column, labelled "Rename column 2 (full_name)"; no grid |
| Progress, no cancel | Works | The wording "Sent to the server; it can't be stopped now" before the click and in the spinner; a per-call timeout of 600 s; a timeout is reported as *unknown*, not as a failure, because the server may have finished |
| Several files | Works | Each file has its own preview and mapping; "Upload all" sends them in turn |
| Mode | Works | A file that matches a T&E table starts as a T&E load, which sends none of what the API rejects there |
| Results | Works | Imported, partly imported (row errors, error report CSV and XLSX, logs), already imported, failed, unknown |
| Endpoint | The direct one, as React | The direct one. The staged path (`POST /api/csv/uploads`, then `/submit` and `/approval`) has no React screen and would be new work with its own roles |

**7. Strains from the spike**, with a proposal for each, and what was done:

| Strain | Proposal | Done |
|---|---|---|
| No click-to-edit on a cell | Keep row selection, and add a plain "Row number" input beside it | Done (#267) |
| Save enables only on Enter or blur | `st.form`, and refuse an empty reason on submit | Done (#267) |
| No per-cell tooltips | Keep the original value in the row detail panel | Done (#267) |
| Whole script re-runs on every action | `st.cache_data` with a short TTL, keyed by the session token | Done on every list; the caches are cleared after an upload and on sign-out, so a new import shows everywhere at once |
| Limited styling | Accept | Accepted |
| Deprecated arguments | Use `width="stretch"` and pin the Streamlit version | Done: `streamlit==1.67.0`, pinned in two files that a test keeps in step |

**8. Tests: both.** Checked on the spikes: `AppTest` runs a screen headless with a faked API and tells an uploader ("read-only for your role") from a reviewer, so role gating, captions, error text, filters and the outcome rules are fast tests. It has **no way to select a dataframe row, drive dialogs, or use `st.file_uploader`**, so each screen keeps its logic in a function a test can call (the upload screen's `show(files)`), and the browser tests (Playwright) cover the dialogs, the grid and the uploader itself. Where they run: the `AppTest` tests run in the free-tier job, with Streamlit and `openpyxl` in `requirements-dev.txt`; that job took about 36 s before Streamlit and 61 s to 69 s in the runs since. The browser tests need Chromium and a Postgres, and run in their own `browser` job (#273) through `scripts/test_report.py --paths e2e --strict`, so every test is accounted for and a skip fails; it has been a required check on `main` since 24 Nov (see "Owner decisions"). The 186 vitest tests go away screen by screen as the React code is deleted.

**9. Parked issues.** #176 (fixed in #235) and #179 disappear with the React code. #186: the rename UI is on the upload screen, and the error report carries the renames that were sent. #187: the review screen's upload picker lists every attempt, failed ones included. #188: no Cancel button; the screen says "sent to the server, can't be stopped", as React does. #242: the upload screen sends `typesConfirmed` for the types the person confirmed, and not in T&E mode, where the API refuses it.

## Corrections (18 Nov)

Found while filing the implementation issues; they changed what the plan said or left out.

1. **The React "audit" screen is not the server's audit log.** `audit.tsx` is the browser's own import history, kept in `localStorage`: filters by file name, status and date, a per-import error view, bulk selection, CSV and XLSX downloads, and an "App changelog" list (`audit-log.ts`, a developer changelog kept as a constant). Step 3 therefore builds the history from `GET /api/csv/uploads` and `GET /api/csv/uploads/{id}`: it then belongs to the tenant and survives browsers and devices, and no `localStorage` is involved, so the #176 class of leak cannot recur. **Behaviour change for users: the history is no longer per browser.** Every export keeps the formula-injection guard from #193. *(The claim that the server's audit log has no screen in React was true on 18 Nov and is out of date: see correction 4.)*
2. **The accessibility CI job (#168, `tests/accessibility/`) scans the React dev server.** Deleting React (step 6) leaves that job with nothing to scan, so it needs a Streamlit equivalent or a deliberate decision to retire it, settled before the React app goes. See correction 7 for what the build learned.
3. **Saved mapping templates need a home.** They are kept per tenant and user in the browser since #235, and Streamlit has no `localStorage`. Options: drop them, keep them for the session only, or store them server-side (which needs API work). This belongs to the upload screen (step 4).

## Corrections (19 Nov)

Found while building steps 2 to 4.

**4. The React history page now shows the server's audit events.** PR #261 (merged 18 Nov) added a "Server audit events" panel (BR-35), so only `GET /api/audit/log` and `/api/audit/verify` have no screen anywhere. The Streamlit Import history page has a matching "Server audit events" view for roles that may read the audit log (`GET /api/audit/events`: filters by actor, action, file and date, pages of 100, and the server's own CSV). It follows the React page, so it needs no separate decision; the owner decided on 24 Nov not to build a page for the log and its verification (see "Owner decisions").

**5. What was dropped, on the plan's defaults** (saved mapping templates and the "App changelog" were confirmed by the owner on 24 Nov, see "Owner decisions"; the rest were not asked about separately): saved mapping templates, the "App changelog", bulk selection and "Retry" on the history page (an import is retried from the upload screen), "Print / save as PDF", and the header-mapping and cancellation columns of the report (the server does not store them).

**6. Text from a file or a person is a stranger's, and Streamlit reads more of it as Markdown than expected.** `st.table` renders a cell as Markdown (a file name `[x](https://...)` became a link in a browser test); widget labels, expander titles, buttons and spinners are Markdown too, and Streamlit uses a label as a box's `aria-label` exactly as written. Backslash-escaping is not enough: a bare `https://` still links. The rule now: every such text goes through `review_model.literal` (an inline code span), and the labels of per-column boxes are cut down to letters, digits and spaces (`column_label`). Each screen has tests for it. Any new screen must follow it.

**7. Accessibility input for #257.** `st.dataframe` is drawn on a canvas, so a screen reader and the axe scan cannot see it; `st.table` is HTML. The review grid has to be a `st.dataframe` (it is editable by selection), which is why the "Row number" input exists; the history and imported-files lists are `st.table`; the imported table preview is a `st.dataframe`, so what it shows is invisible to axe. The accessibility job needs a decision on what it scans, and it cannot see inside the grids whichever way it is rebuilt.

**8. Rules the upload work settled** (the API's behaviour, not a design choice): the same bytes are `duplicate_file` whatever the file is called; the same name with new bytes is the next version of the dataset (the `overwrite` flag is ignored since M5); a file that is not UTF-8 is refused with the reason, not decoded with replacement characters; two files with the same bytes under two names are two separate files on the screen (they used to share a widget key and crash it); the picker of imported files includes the table name, because versions share a file name.

## Owner decisions

The build used the defaults below before the owner had answered. On 24 Nov the owner confirmed every one of them, so the build needs no change.

| Question | Decision | Confirmed |
|---|---|---|
| Whole-app or per-screen cutover | Whole app, with React kept for one release as the rollback | 24 Nov |
| OIDC sign-in in the UI | Not built | 24 Nov |
| Saved mapping templates | Dropped: renames apply to one upload | 24 Nov |
| "App changelog" | Dropped: release notes do the job | 24 Nov |
| Server audit events | Kept on the history page, as React has it | 24 Nov |
| The server's audit log and its verification | No page (`GET /api/audit/log` and `/verify` stay API-only) | 24 Nov |
| About 116 MB more in the offline bundle | Accepted | 24 Nov |
| Accessibility job | Scans the Streamlit app as well as React (#388, merged 24 Nov), with no recorded Streamlit violations after the caption-contrast fix. The React scans go with React in step 6 | 24 Nov |
| Where it runs in Azure | Azure Container Apps, in the existing internal environment (`cae-te-prod`): one always-on app for the API and one for Streamlit, reachable from the private network only, with no public address. See "Azure host" below | 24 Nov |
| `browser` job (#273), and the accessibility job, as required checks | Both required, with the three Quality Gate checks, on a protected `main` (see `DECISIONS/2026-11-02-main-branch-protection.md`, "Applied, 24 Nov 2026") | 24 Nov |

Nothing is left for the owner in this record.

### Azure host (decided 24 Nov)

`infra/terraform-prod` today runs only the migration batch job (a Container Apps job); it deploys no API and no front end (F9 in `docs/SECURITY_REVIEW_PACK.md`). The owner chose to add both to the same Container Apps environment, which is already internal-only (`internal_load_balancer_enabled = true`), rather than an App Service plan or keeping the web app out of Azure. Users reach it from inside the Azure network (VPN, ExpressRoute or a jump host); it gets no public address, since sign-in is by password only (no OIDC).

What the build (the Azure half of #256) has to do and check:

- Two `azurerm_container_app` resources, API and Streamlit, from images in the existing registry, using the existing managed identity, Key Vault secrets and Log Analytics workspace. The API talks to the private PostgreSQL; Streamlit gets `API_URL` set to the API's internal address and `MAX_UPLOAD_BYTES` set to the API's value.
- Streamlit: internal HTTP ingress, **one replica minimum** (no scale to zero, which would drop sessions and add a cold start) and **sticky sessions** if it ever runs more than one replica, because a session lives in that replica's memory.
- Not verified yet: that WebSockets stay open through the internal ingress for a long review session, and that a 50 MiB upload passes the ingress. Test both before cutover.
- Rough added cost: two small always-on apps, about AUD 40 to 70 a month on top of the ~AUD 285 already estimated in `infra/terraform-prod/main.tf`.

## Not verified

- Telemetry off means no outside connection (step 5 of the dry run); WebSocket pass-through behind a proxy; the app open in two browser tabs.
- Upload size: the limits were tested at their edges (a file between Streamlit's limit and the API's is refused by the app, and the API itself refuses just over its limit). A successful import of a file near 50 MiB, its memory (a file is held as bytes, text and base64 before it is sent) and its time were not measured; the 600 s upload timeout is tested with a fake, not by waiting.
- XLSX reports were read back with `openpyxl`, not opened in Excel (#244).
- Streamlit's behaviour at the larger row counts of #210.
- The browser tests ran against a throwaway Postgres, three times in a row without a failure; the `browser` job (#273) now runs them in CI, so a regression is reported on the pull request, and since 24 Nov it is a required check, so a failure blocks the merge.

## Issues filed (18 Nov), on this plan's defaults

Issues: #251 App shell (step 1) · #252 Review screen (step 2) · #253 Import-history screen (step 3) · #254 Upload spike (step 4) · #255 Upload screen (step 4, after the spike) · #256 Packaging for the offline bundle and Azure (step 5) · #257 Cutover and deletion (step 6) · #258 AppTest and browser tests.

The #254 spike was the gate and passed ("limiting, with workarounds"), so #212 stays as it is. The next gate is the owner's answer on Azure and the #60 dry run, before #256.

## Related

Issues #212, #251 to #258 (the implementation issues), PRs #264, #265, #267, #269, #270 (the build), #261 (the server audit events panel in React), #154 (spike), #60 (offline dry run), #242 (confirmed types), #244 (the XLSX check in Excel), #168 (accessibility job), #193, #187, #188, #176, #210
