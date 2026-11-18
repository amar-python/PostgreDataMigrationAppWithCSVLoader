# #254 spike: the upload and preview screen in Streamlit

Throwaway learning code. The React screen (`csv-table-hub-main/src/routes/_authenticated/index.tsx`) stays live.
Nothing here is wired into CI, the build or the offline bundle. It reuses the app shell's sign-in and session
handling (`streamlit_app/`, #251) and nothing else.

## Outcome: limiting, with workarounds

**Streamlit can carry this screen.** Every question below has a working answer against the real API, checked
in a browser (`e2e/test_streamlit_upload_spike.py`, 11 tests). Nothing found makes it *wrong for this screen*,
so the plan's whole-app cutover assumption (#212) stands. It is "limiting" because three things need a
decision or a workaround before the real screen (#255) is built; they are listed under "What strained".

## Run it

With the API on `localhost:8000` and the shell's requirements installed:

```bash
pip install -r spikes/streamlit_upload/requirements.txt
cd spikes/streamlit_upload
python -m streamlit run app.py
```

Sign in with an account that may upload (uploader or tenant admin). `API_URL` says where the API is.

## The seven questions

| # | Question | Result |
|---|---|---|
| 1 | Size limit | **Cannot be made equal with one setting.** See "What strained", 1. The API refuses over 50 MiB with `413 "File too large"`; the uploader refuses over `server.maxUploadSize` with "File must be 50.0MB or smaller." and offers no Upload button. |
| 2 | Column mapping | **Works two ways.** `st.data_editor` (rename column + type dropdown, `num_rows="fixed"`) and an ordinary-widgets form (a text box and a select per column). Both reach the database: the renamed header is the table's column, the chosen type is the column's `data_type` (read from `information_schema`, not from the API's reply). The Upload button stays disabled until "I have checked the column names and types" is ticked, and then `types` and `typesConfirmed: true` are sent (#195, #242). |
| 3 | Progress, no cancel | **Works.** "Sent to the server; it can't be stopped now" (the React app's wording) is shown before the click and in the spinner during it (checked with a 40,000-row file). There is no Stop button. The tab's script is busy until the API answers. |
| 4 | Several files | **Works.** Each file gets its own preview and mapping; "Upload all" sends them in turn with a progress bar. Streamlit holds the files in memory and re-runs the whole script on every click, so the previews are cached per file hash. |
| 5 | Mode | **Works.** A T&E-shaped file (`orgs_sample.csv`) preselects "Test and Evaluation table" from `teTableMatch`; the target list is `GET /api/te/tables`. The mapping editor and the confirm box are not shown in T&E mode, so the API's 422 for a header mapping or `typesConfirmed` there cannot be triggered from this screen. |
| 6 | Results | **Works.** Rows imported and failed; the row errors as a table (6 of 10 imported, 4 failed, with the reasons); the same bytes again: "Already imported as ... nothing was changed"; the same name with changed content: "Version 2 of dataset ...". The stored original's SHA-256 equals the hash of the file the person chose (#185). |
| 7 | Which endpoint | **The direct one, `POST /api/csv/upload`.** That is what the React app uses. The staged path (`POST /api/csv/uploads`, then `/submit`, `/approval`, `/import`) exists, but the React app has no screen for it (it only lists and reads attempts), so parity does not need it. A staged screen would be new work with its own roles: uploader submits, reviewer approves. |

## What strained

1. **The size limits are separate and not equal.** The API's limit is `MAX_UPLOAD_BYTES`, 50 MiB (52,428,800
   bytes) of text. Streamlit's `server.maxUploadSize` is an integer count of megabytes, and it counts a
   megabyte as 1,000,000 bytes: with it set to 50, a 49.9 MB file is accepted and a 51 MB file is refused,
   though the API would take the 51 MB file. No integer makes them equal. The API does not publish its limit,
   so the front end cannot read it. **Workaround:** set Streamlit's limit above the API's (53) and check the
   real number in the app, from the same `MAX_UPLOAD_BYTES` environment variable, with a message in the app's
   own words. Deployers then set one variable for both.
2. **The grid editor is drawn on a canvas.** In a browser test a cell can only be reached by clicking
   coordinates, and a keystroke sent before the cell editor has opened is dropped without any error (the first
   attempt renamed nothing and the import still succeeded). The headless `AppTest` was not tried on it, and
   screen-reader access was not tested; the accessibility job (#168) scans the DOM and cannot see inside a
   canvas. **Workaround:** make the ordinary-widgets form the default (it has labels and roles, and the tests
   find its controls by name), and show row errors with `st.table` rather than `st.dataframe`. Keep the grid
   only if wide files make a widget per column unwieldy (the API allows up to 1,000 renames).
3. **The screen is busy while an import runs, and the shell's 30 s timeout is too short for a big one.** The
   spike sets `api_client.TIMEOUT_SECONDS = 600`. The real screen needs a per-call timeout on
   `api_client.request`; a timeout does not stop the import on the server, which is the "can't be stopped" case.

Smaller: the whole script re-runs on every interaction (the previews are cached by file hash); `st.file_uploader`
keeps a file after upload, so a repeat click re-sends it (the API's duplicate check answers); the uploader's
message names a size (in megabytes) where the API's ("File too large") names none.

## Not done, and not verified

- **Saved mapping templates** (kept per tenant and user in the browser today, and Streamlit has no
  `localStorage`) need an owner decision first: drop, session-only, or server-side. They are not in this spike.
- **Memory.** A file is held as bytes, decoded text and base64 at once before it is sent, so a file near the
  limit needs several times its size. Not measured.
- **Large files end to end.** The biggest import run here was 40,000 rows. The row cap and the time for a file
  near 50 MiB were not exercised.
- **Behind a proxy**, WebSockets, and several browser tabs at once: not tested (the plan lists them as untested).
- **A file that is not UTF-8:** the spike decodes with replacement characters, as `file.text()` does in the
  React app. Not compared with it on a real file.
- The tests are not wired into CI, like the other browser tests (`e2e/README.md`).
