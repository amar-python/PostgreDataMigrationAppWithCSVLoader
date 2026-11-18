# Decision: Plan for moving the frontend from React to Streamlit (#212)

Status:  Proposed, for the owner to accept or change (nothing here is decided)
Date:    2026-11-16
Review:  When the upload-screen spike (step 4) is done: its outcome can change the order or the whole plan

## Choice

Build the Streamlit app as a whole, screen by screen, and **switch over once, not screen by screen**. Keep the React app running for one release as the rollback, then delete it.

| Step | What | Replaces (React lines, non-test) |
|---|---|---|
| 1 | App shell: sign-in, session expiry, role gating, sign-out that clears state, change password | `auth.tsx` 100, `session.ts` 128, `change-password.tsx` 121, `session-menu.tsx` 31, `__root.tsx` 126 |
| 2 | Review screen: productionise the #154 spike | `review-table.tsx` 356, `review.$uploadId.tsx` 33 |
| 3 | Audit screen | `audit.tsx` 254, `audit-log.ts` 35 |
| 4 | **Spike** the upload screen (2 days, like #154), then build it | `_authenticated/index.tsx` 810, `csv-preview.ts` 165, `job-outcome.ts` 168, `export.ts` 271, `mapping-templates.ts` 73, `use-local-storage.ts` 46 |
| 5 | Package it for the offline bundle and Azure; switch the default URL | `csv.functions.ts` 372 (the API client) goes last |
| 6 | One release later, delete `csv-table-hub-main/` | all of the above, about 3,300 lines and 20 test files |

Why this order: the shell is needed by every page, so it comes first; review is already spiked; audit is read-only and low risk; upload is the largest and least proven screen, so it gets its own spike before anything is committed to.

## The nine questions from #212

**1. Order.** As above.

**2. Cutover: whole app, not per screen.** The React app keeps its session token in `sessionStorage` on its own origin; Streamlit keeps it in `st.session_state` on another. Running both per screen would make users sign in twice. Both talk to the same API, so there is no data migration, and rolling back is pointing the URL back at React.

**3. Auth and sessions.** The React app has local sign-in only (it has no OIDC code, though the API does: `/api/auth/oidc`). So parity needs only `/api/auth/login`, as the spike already does. If OIDC in the UI is wanted later, Streamlit 1.67 can do it: `st.login()` with `expose_tokens = "id"` in `secrets.toml` gives `st.user.tokens["id"]`, which is what `/api/auth/oidc` takes. It needs the `streamlit[auth]` extra (7 more packages). Session expiry: the spike already clears the session on a 401; the shell should also check `expiresAt`.

**4. Offline install (#60).** Measured with the same `pip download` flags `scripts/offline/build_bundle.sh` uses (CPython 3.12, manylinux x86_64, binary wheels only):

| Wheel set | Wheels | Size |
|---|---|---|
| API today (`api/requirements.txt`) | 30 | 25 MB |
| `streamlit` | 34 | 117 MB |
| `streamlit[auth]` | 41 | 123 MB |

Only 10 packages overlap with the API's set, and they are small (0.9 MB), so the bundle (143 MB today) grows by **about 116 MB, to roughly 260 MB**, less whatever the Node runtime and the prebuilt frontend take out (not measured). Every package is a binary wheel and `pip install --no-index --find-links` resolves the whole set offline (checked with `--dry-run`). `install.sh` swaps the `te-frontend` unit for a `te-streamlit` unit, and the API address becomes an environment variable, so the `__OFFLINE_API_BASE__` rewrite goes away. Telemetry defaults to **on** (`gatherUsageStats = true`) and is switched off with `browser.gatherUsageStats = false`; **that it then makes no outside connection was not tested** and must be, on the dry-run VM. Sequence: do the #60 dry run on the current React bundle first, since it stands alone and is overdue; change packaging afterwards, not at the same time.

**5. Deployment.** On-premises it is one more systemd unit, like `te-frontend` now. In Azure, `infra/terraform-prod`, the Dockerfile and the entrypoint define no frontend at all today, so Streamlit adds a service there rather than replacing one, and the owner needs to say where it should run. Anything in front of Streamlit must pass WebSockets through; this was not tested.

**6. Upload and preview screen: needs its own spike** before steps 4 and 5 are committed to. Things to prove: the uploader's size limit (Streamlit defaults to 200 MB, the API refuses over `MAX_UPLOAD_BYTES`, 50 MB, so they should agree); an editable column-mapping table (`st.data_editor`); progress while the server works, with no cancel (see #188); several files at once; sending `typesConfirmed` (#242). Outcomes, as for #154: fine, limiting, or wrong for this screen.

**7. Strains from the spike**, with a proposal for each:

| Strain | Proposal |
|---|---|
| No click-to-edit on a cell | Keep row selection, and add a plain "Row number" input beside it. The grid is drawn on a canvas, so selection is also the brittle part of the browser tests |
| Save enables only on Enter or blur | Put the dialog's fields in an `st.form`, and refuse an empty reason on submit (the API already returns 422) |
| No per-cell tooltips | Keep the original value in the row detail panel, as the spike does |
| Whole script re-runs on every action | `st.cache_data` with a short TTL for the uploads list, keyed by the session token |
| Limited styling | Accept |
| Deprecated arguments | The spike uses `use_container_width`, which Streamlit 1.67 reports as past its removal date. Use `width="stretch"` and pin the Streamlit version |

**8. Tests: both.** Checked on the spike: `AppTest` runs it headless with a faked API and tells an uploader ("read-only for your role") from a reviewer, so role gating, captions and error text can be fast tests. It has **no way to select a dataframe row or drive dialogs**, so edit, exclude and history stay in Playwright (`e2e/test_streamlit_spike.py`, 4 tests, stable after hardening). The 186 vitest tests go away screen by screen as the React code is deleted.

**9. Parked issues.** #176 (fixed in #235) and #179 disappear with the React code. #186: the API half is done; the rename UI comes with the upload screen. #187: the spike's upload picker already lists every attempt, failed ones included; it carries over with the review screen. #188: no Cancel button; say "sent to the server, can't be stopped", as React now does. #242: the upload screen must send `typesConfirmed` for the types the user confirmed.

## What the owner decides

1. Whole-app cutover (this plan) or per screen, accepting a second sign-in?
2. Is OIDC sign-in in the UI wanted? (Not needed for parity.)
3. Where should the Streamlit app run in Azure?
4. Is about 116 MB more in the offline bundle (143 MB to roughly 260 MB) acceptable?

## Not verified

Telemetry off means no outside connection (step 5 of the dry run); WebSocket pass-through behind a proxy; upload-size behaviour; Streamlit's behaviour at the larger row counts of #210.

## If accepted, file these issues

Shell (step 1) · Review (step 2) · Audit (step 3) · Upload spike (step 4) · Upload screen · Packaging and `install.sh` (step 5) · Cutover and deletion (step 6) · AppTest suite for the Streamlit screens.

## Related

#212, #154 (spike), #60 (offline dry run), #242 (confirmed types), #187, #188, #176, #210
