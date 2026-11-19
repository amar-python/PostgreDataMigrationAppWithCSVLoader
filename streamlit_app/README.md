# Streamlit front end (migration steps 1 to 3: the app shell #251, review #252, import history #253)

Part of the plan in `DECISIONS/2026-11-16-streamlit-migration-plan.md` (#212). **The React app in
`csv-table-hub-main/` is still the live front end.** This app is not wired into CI, the Docker image
or the offline bundle yet; that is step 5 (#256).

What exists so far: sign-in, session expiry, sign-out, change password, a home page that says what the
signed-in role can do, the **Review** screen and the **Import history** screen. The upload screen comes with #255.

## Run it

With the API running on `localhost:8000` (`scripts/start-api.ps1`):

```bash
pip install -r streamlit_app/requirements.txt
cd streamlit_app
python -m streamlit run app.py
```

Open <http://localhost:8501> and sign in with a tenant account (see `docs/QUICKSTART.md`, "Create your sign-in").
Run it from this folder: Streamlit reads `.streamlit/config.toml` from where it is started, and that file
turns usage statistics off (they are on by default).

`API_URL` says where the API is, for example `API_URL=http://api.internal:8000`.

## How it behaves

- **Sign-in** uses `POST /api/auth/login`, with the same wording as the React app for a wrong tenant,
  username or password. Nothing is written to the browser's storage: the session is held by Streamlit on
  the server for that browser tab.
- **Expiry:** a session past its `expiresAt` is signed out on the next click. **Any 401** from the API
  also ends the session, with "Your session has ended. Sign in again."
- **Sign-out** calls `POST /api/auth/logout` (best effort) and clears *all* session state and the caches,
  so nothing is left for the next person (#176).
- **Roles:** the permission table in `auth.py` is a copy of `api/auth.py`, and a test fails if they drift.
  The home page lists what the role can do; later screens appear only for roles that can use them. The
  API remains the enforcer.
- **Change password** uses `POST /api/auth/password`. This session stays; the server ends the others.

## The Review screen (#252)

Replaces the React review screen (`review-table.tsx`). Pick an upload (every attempt is listed, failed and
partly failed ones included, with an "Only failed or partly failed" filter; a rejected file stored no rows, so
there is nothing to review), then a row, by selecting it in the table **or** typing its number in the
"Row number" box. The table is drawn on a canvas, so the box is what keyboard and screen-reader users use.

- Each row shows why it is invalid (the database's own reason for a rejected T&E row too, #190), what was
  edited, and its decision. **Edit a cell** and **Exclude/Include row** are forms: Enter saves, and a missing
  reason is refused before anything is sent. **History** lists every change, who made it and why.
- Roles that cannot review (uploader, auditor) can look and read the history, and are told so.
- Changes are saved with the upload for review; they do not change the imported table (M4a, #108).
- The list of uploads is cached for 30 seconds, per session ("Refresh the list" fetches it again). Rows are
  never cached.
- **Text from a file is shown as written.** A cell, a file name or a reason is put in a code span, so a cell
  such as `[click here](https://example.test)` or `**bold**` cannot become a link or formatting in front of a
  reviewer. (Escaping the punctuation was tried first and was not enough: Streamlit still links a bare URL.)
- Not carried over from the React screen: a link straight to one upload's review (`/review/<id>`).

## The Import history screen (#253)

Replaces the React "Import history" page. **Behaviour change for users: the history is no longer per browser.** The
React page was the browser's own record, kept in `localStorage`; this one reads the server's
(`GET /api/csv/uploads`, `GET /api/csv/uploads/{id}`), so it is the tenant's, shows imports from any browser or
device, and nothing about it is kept in the browser (a browser test checks the browser's storage).

- **List:** every upload attempt, newest first, 25 to a page, filtered by file name, status, uploader and a date
  range (the whole "to" day is included). Times are UTC.
- **One import:** choose it to see why rows failed (the server keeps the reasons for the first 200 only, and the
  screen says so), the server's step log, and the **error report** as CSV or XLSX.
- **A report of all matching imports** (CSV and XLSX, up to 5,000; a longer one says it was cut short).
- **Server audit events** (`GET /api/audit/events`, BR-35), for roles that may read the audit log: filter by actor,
  action, file and date, page by 100, and download the server's own CSV.
- **Reports** carry the formula-injection guard from #193: a cell that starts with `=`, `+`, `-` or `@` (and is not a
  plain number) gets a leading quote, in CSV and in XLSX (which stores it as text, never as a formula). The XLSX also
  survives a control character in a value (openpyxl refuses one) and cuts a value to the 32,767 characters Excel
  keeps. The visible apostrophe in XLSX is the #193 decision, still to be checked in Excel (#244).
- **Not carried over from React:** bulk selection and "Retry" (an import is retried from the upload screen),
  "Print / save as PDF" (print the page), the in-app "App changelog" (release notes do that job), and the header
  mapping and cancellation columns of the report (the server does not store them).
- **Tables are `st.table`**, which is real HTML (a screen reader and the accessibility scan can read it, and a
  browser test can assert on it). `st.table` reads a cell as **Markdown**: a cell holding `[x](https://...)` became
  a link in a browser test. So every text from a file goes through `review_model.literal`. `st.dataframe` is safe
  from that (it draws on a canvas) but a canvas is invisible to a screen reader and an accessibility scan.

## Tests

- `tests/unit/test_streamlit_{shell,review,history,exports,api_client}.py`: fast, headless
  (Streamlit's `AppTest`, a faked API). Run with the unit tests.
- `e2e/test_streamlit_{shell,review,history}.py`: in a real browser, against the real API
  (what `AppTest` cannot do: click the table, a session the server ends, how a browser shows a cell's text).
  Run like the other end-to-end tests (`e2e/README.md`); not part of CI.
