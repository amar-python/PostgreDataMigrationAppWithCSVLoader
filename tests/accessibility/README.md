# Accessibility scans (#168)

WCAG 2.1 level A and AA checks of the frontend (`csv-table-hub-main`), run with
[axe-core](https://github.com/dequelabs/axe-core) in Chromium through Playwright, against the
Vite dev server. They run in their own CI job, `accessibility` in
`.github/workflows/quality-gate.yml`, and nowhere else: the integration job runs with
`-m "not accessibility"`.

## Run them

```bash
pip install -r requirements-a11y.txt
python -m playwright install chromium
(cd csv-table-hub-main && npm ci)

python -m pytest tests/accessibility -v        # or: make test-accessibility
```

The scans start `npm run dev` themselves on a free port and stop it afterwards. Missing
Playwright, Chromium or `node_modules` fails the run with the command to fix it; it is never a
skip.

| Variable | Effect |
|---|---|
| `A11Y_BASE_URL` | Scan a frontend that is already running instead of starting one |
| `A11Y_CHROMIUM_PATH` | Use this Chromium instead of the one `playwright install` fetched |
| `A11Y_REPORT_DIR` | Write one JSON file per scenario with every violation axe-core found (CI uploads these as the `accessibility-report` artifact) |

## What is scanned

The API is stubbed in `stub_api.py`: no database, no API process. Every `/api/**` request gets a
fixed answer and a signed-in session is planted in the browser. A request the stub has no answer for fails the
test, so a new endpoint in the frontend is noticed here instead of silently scanning a half-rendered page. A backend-only change therefore
cannot alter what is scanned, and the job needs no PostgreSQL service.

| Scenario | State |
|---|---|
| `sign_in`, `sign_in_failed` | the sign-in page, and after the server refuses a login |
| `upload_page_empty` | a new tenant: no files, no import history |
| `upload_page_with_history` | a migrated file and one import of each kind (done, failed, duplicate) |
| `upload_page_failed_attempts` | the list of every upload attempt, with a failed, a partly imported and a rejected one |
| `upload_mapping_dialog` | the dialog that opens when a CSV is chosen |
| `upload_page_toast` | the toast shown when a non-CSV file is chosen |
| `audit_log_with_history`, `audit_log_report_menu` | the audit log, and with its report menu open |
| `review_page` | the review screen for one stored upload |

Each test waits for content that proves the page rendered before it scans. A page that
redirected to sign-in or showed an error would otherwise scan clean and pass for the wrong
reason. `test_signed_out_visitors_are_sent_to_sign_in` guards the redirect itself.

Not covered: dark mode, mobile widths, keyboard-only flows (axe-core checks markup, not whether
a task can be completed), and the Streamlit spike (#154).

## Known violations, and why the job passes today

The frontend has accessibility problems, and fixing them is separate work (out of scope for
#168). A scan that fails on any violation would keep the job red until then, and a job that is
always red gets ignored. So `known_violations.json` records what is wrong now, per scenario and
rule with an element count, and each scan fails on a **change**:

* a rule that fails where it is not recorded, or on more elements than recorded: **fails**
  (a regression);
* a recorded rule that no longer fails: **fails** until its entry is deleted, so the list can only
  get shorter. The message names the entry;
* fewer elements than recorded: reported only. Lower the number when convenient.

When a frontend change fixes a violation, delete its entry in the same pull request. To see the
whole picture, including what is recorded, set `A11Y_REPORT_DIR` and read the JSON, or run with
`-s` to print the known violations.

**To make the job strict instead** (red until the frontend is fixed), empty the `violations`
list. That is the only change needed.

The recorded violations are the ones the closed PR #41 bundled with its scan: unnamed selects and
icon-only buttons, unnamed upload progress bars, and low-contrast text (including the error
toast).

## A frontend bug these scans work around

In development, React StrictMode runs the effects in
`csv-table-hub-main/src/hooks/use-local-storage.ts` twice: the first pass writes the hook's empty
default over the stored import history, and the second reads that back, so saved history is never
shown after a reload. Production builds do not double-run effects. `stub_api.seed_script`
drops writes of `[]` to that key so the audit page can be scanned with rows in it; without that, the
page was scanned empty and passed without checking a single row. Remove the guard when the hook is fixed.
