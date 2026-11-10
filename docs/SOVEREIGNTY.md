# Sovereignty, classification and performance (M7, #111)

BR-35, BR-37 and decisions 7 and 8. What the platform promises about where data goes, how it is marked, how long the audit trail is kept, and how fast it runs.

## No runtime external services (BR-37)

The application makes no outbound calls at run time. Three checks back that up. None replaces the offline install rehearsal in `docs/offline-install.md` (#60).

| Check | What it proves | Run with |
|---|---|---|
| Static scan (`tests/unit/test_sovereignty.py`) | The API imports no HTTP client and names no external host; the frontend source names none (apart from an XML namespace) and depends on no analytics package | `make test-unit` |
| Egress-blocked run (`tests/egress_guard.py`) | The API tests pass with every in-process connection that isn't to this machine refused and recorded. A swallowed attempt still fails the run | `make test-egress-blocked` (also a CI step) |
| Built-bundle scan (`scripts/check_bundle_egress.py`) | The built frontend, client and server, can't load a script, stylesheet, font or URL from outside, and names no analytics or CDN host | `make check-bundle`, after `cd csv-table-hub-main && npm ci && npx vite build` |

Run on 2026-11-09: the client bundle names 13 hosts and the server bundle 24, all XML namespaces and documentation links that are never requested; no load paths and no analytics or CDN hosts in either.

**The one external call.** With `OIDC_ISSUER` set and an `https://` `OIDC_JWKS_URL`, the API fetches the IdP's signing keys (PyJWT, `api/oidc.py`). The IdP is one the deployment controls, and an air-gapped install uses a `file://` key file or local accounts instead. Nothing else.

**What the egress guard can't see.** It patches Python's sockets, so it covers the API and the tests. libpq connects below Python (the guard refuses a database host that isn't local instead), and child processes such as `psql` and the shell loaders aren't covered. For an on-premises rehearsal, block the network itself, for example in a network namespace or with a firewall rule, and run `make test-system`. Don't do that on a hosted CI runner: it needs the network to report its results.

## Classification and retention (decision 7)

Per deployment (ADR-0003), set by environment variable (`docs/ENV_VARIABLES.md`):

- `DATA_CLASSIFICATION`, default `OFFICIAL: Sensitive`. Every API response carries it in `X-Data-Classification`, so anything saved from the API can be marked. The browser can read it (CORS exposes the header). `GET /api/policy` returns it with the retention. `PROTECTED` is refused at startup.
- `AUDIT_RETENTION_YEARS`, default 7. Triggers reject any change to audit rows and preserved originals, so nothing in the app deletes them. Any purge is an operator action outside the app and must keep audit rows at least this long. Raw uploads are kept until a recorded purge, which doesn't exist yet.

## Filtered audit reports (BR-35)

`GET /api/audit/events` (tenant admin and auditor): filter by `actor`, `action`, `file` (name contains), `table`, `from` (inclusive) and `to` (exclusive), page with `limit` and `offset`, or download with `format=csv`. The CSV neutralises spreadsheet formulas the way the frontend export does. `GET /api/csv/uploads` takes `status`, `uploader`, `file`, `from` and `to`, and says why a failed, rejected, duplicate or partly imported attempt came out that way (`failure_reason`).

The frontend audit page doesn't call these yet.

## Performance (decision 8)

Targets, on a 2 vCPU / 4 GB instance: a 100,000-row import under 60 s, and the first preview page under 2 s.

`python scripts/perf_import.py --rows 100000 --enforce` runs the whole flow (preview, stage, review page, submit, approve, import) in a throwaway tenant and prints timings and the hardware. `tests/performance/test_import_scale.py` runs it as a smoke test, and asserts the targets only with `PERF_ENFORCE=1`.

Measured 2026-11-09 on a 4-CPU, 15.7 GB machine, 100,000 rows (9.8 MB, 8 typed columns):

| Step | 4 CPUs | Pinned to 2 CPUs |
|---|---|---|
| Preview (first page, whole file) | 0.26 s | 0.23 s |
| Stage (store original and rows) | 6.1 s | 5.7 s |
| First review page | 0.03 s | 0.03 s |
| Approve (validates every row) | 1.6 s | 1.6 s |
| Import (COPY and promote) | 3.1 s | 3.1 s |
| **Stage to imported** | **10.8 s** | **10.3 s** |

The API process peaked at 424 MB. Pinning the API and PostgreSQL to two CPUs approximates the reference CPU limit but not its memory, so **this is evidence, not proof, for the reference instance**: the run on a real 2 vCPU / 4 GB instance is still to do (`--enforce`).

The preview took 1.66 s before M7: parsing every row of a large file in Python to show ten. It now parses only the head of a file over 200,000 characters and counts the rest with the C `csv` reader, so `totalRowsApprox` is the approximation its name says.
