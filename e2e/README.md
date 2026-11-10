# Browser end-to-end tests

Playwright (Python) against the real API, the React app and the Streamlit spike, in Chromium.
They cover what the vitest and pytest suites cannot: #176, #187 and #188 in a real browser, and the #154 Streamlit review screen.

Not part of the default `pytest` run (`testpaths = tests`) and not wired into CI: they need three
local servers and a browser. (The accessibility scans have their own CI job, #168.)

## Run

PostgreSQL must be reachable as for the integration tests (`PG*` environment variables), the dev
database deployed (`bash build/deploy_all.sh dev`), and ports 8000, 8080 and 8501 free.

```bash
pip install playwright streamlit && playwright install chromium
(cd csv-table-hub-main && npm ci)
pytest e2e -p no:cacheprovider
```

To use a Chromium you already have, set `E2E_CHROMIUM=/path/to/chrome`.

The fixture creates two tenants and four users, builds the React app (`NITRO_PRESET=node-server`, as the offline bundle does) and serves that production build, starts the API and Streamlit, and removes everything afterwards.
The dev server (`vite dev`) is not used: it double-runs effects and hides or invents bugs the shipped app does not have.
