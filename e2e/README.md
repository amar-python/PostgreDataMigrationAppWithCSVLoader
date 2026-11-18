# Browser end-to-end tests

Playwright (Python) against the real API, the React app, the Streamlit spike and the Streamlit app shell (#251), in Chromium.
They cover what the vitest and pytest suites cannot: #176, #187 and #188 in a real browser, the #154 Streamlit review screen, and the shell's sign-in, sign-out and change-password.

Not part of the default `pytest` run (`testpaths = tests`) and not wired into CI: they need four
local servers and a browser. (The accessibility scans have their own CI job, #168.)

## Run

PostgreSQL must be reachable as for the integration tests (`PG*` environment variables), the dev
database deployed (`bash build/deploy_all.sh dev`), and ports 8000, 8080, 8501 and 8502 free.

```bash
pip install playwright streamlit && playwright install chromium
(cd csv-table-hub-main && npm ci)
pytest e2e -p no:cacheprovider
```

To use a Chromium you already have, set `E2E_CHROMIUM=/path/to/chrome`.

Before anything slow starts, the run checks what it needs (`e2e/preflight.py`): Playwright, the browser, Streamlit, the React app's `node_modules`, PostgreSQL accepting connections at `PGHOST`/`PGPORT`, and the four ports. If anything is missing it stops with all of it listed and exit code 3, and a Playwright browser that is not installed says so in one line instead of a stack trace.

The fixture creates two tenants and four users, builds the React app (`NITRO_PRESET=node-server`, as the offline bundle does) and serves that production build, starts the API and Streamlit, and removes everything afterwards.
The dev server (`vite dev`) is not used: it double-runs effects and hides or invents bugs the shipped app does not have.
