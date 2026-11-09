# #154 spike: M4 review screen in Streamlit

Throwaway learning code. The React screen (`csv-table-hub-main/src/components/review-table.tsx`) stays live. Nothing here is wired into CI, the build or the offline bundle.

## Run it

With the API on `localhost:8000` (same as frontend dev):

```bash
pip install -r spikes/streamlit_review/requirements.txt
```

```bash
streamlit run spikes/streamlit_review/app.py
```

Sign in with a tenant account, or leave the sidebar empty in dev to use the shared API key (`API_KEY` env var, no role checks). Set `API_URL` if the API isn't on `localhost:8000`.

## Scope check (issue #154)

| Must support | Result |
|---|---|
| Paging (100 rows) | Page number input. Rows come from `GET /uploads/{id}/rows` |
| Cell edit dialog with reason | `st.dialog`. Save is disabled until a reason is entered (but see strain 2) |
| Exclude / include | `st.dialog` with a required reason |
| History view | `st.dialog`, listing who / when / what / why |
| Role gating | Uploader and auditor see the grid, errors and history only. Reviewer and tenant_admin also get Edit / Exclude |
| Red invalid / blue edited tint | pandas `Styler` backgrounds. Excluded rows are greyed out |
| No new backend code | None. Only existing endpoints are used |

All of it in one ~180-line Python file, with no build step and no Node. Checked end to end with Playwright against a local API (reviewer: edit, exclude and history round-trip; uploader: read-only).

## What was comfortable

- **Every required behaviour worked first try** on standard widgets: `st.dataframe` row selection, `st.dialog`, and `Styler`.
- **Role gating is a plain `if`.**
- **No browser storage.** `st.session_state` lives on the Streamlit server, per tab, and sign-out clears all of it. The class of leak in #176 (tenant A's history in tenant B's `localStorage`) can't happen with this model.
- **One language.** The screen reads like the API code next to it.

## Where it strained

1. **No click-to-edit on a cell.** `st.dataframe` only reports row and column selection, not cell clicks. Editing takes three steps: select the row, click "Edit a cell", pick the column. In React you click the cell. `st.data_editor` edits inline, but it has no hook for a per-edit "reason" dialog.
2. **Save enables on Enter or blur, not on each keystroke.** Streamlit only sends a text input's value when the field is committed. Type a reason and Save stays disabled until you press Enter or Tab. The API still rejects an empty reason (422), so this is a UX issue, not a correctness one.
3. **No per-cell tooltips.** Streamlit doesn't render `Styler` tooltips, so "original value" moved to the row detail panel under the grid.
4. **The whole script reruns on every click.** Each interaction refetches the uploads list and the 100-row page. That's fine locally at 100 rows. It's the model to keep in mind as screens grow.
5. **Styling is limited to colours and backgrounds.** CSS `opacity` is ignored, which is why excluded rows use grey text. The overall look is Streamlit's, not the app's.
6. **It's a new server to deploy:** a Streamlit process (port 8501, WebSocket) next to the API. For air-gapped installs (#60), the wheel ships its pre-built frontend (no Node at build time, unlike Reflex). Set `browser.gatherUsageStats = false`. Offline packaging wasn't tested in this spike.

## Outcome

Choosing the outcome is the product owner's call after trying it (issue #154, "Done when").

My read: strains 1–3 are all on the reviewer's editing path.
- If reviewers mostly look and occasionally fix a cell, Streamlit is fine: **outcome 1**.
- If heavy cell-by-cell editing is the main job, click-to-edit matters, which points to **outcome 2**: NiceGUI, whose AG Grid exposes cell-click events, still in Python.

## What each outcome means for the parked issues

| Issue | Outcome 1/2 (Python-native) | Outcome 3 (keep React) |
|---|---|---|
| #176 localStorage leak | Moot once the screen is replaced (server-side session state) | Server-backed, tenant-scoped history |
| #179 lint baseline | Moot with the React code | `npm run lint -- --fix`, then add to CI |
| #186 header mapping | API side either way. The UI control is rebuilt or dropped | Implement or remove the control |
| #187 failed uploads unreachable | The upload picker here already lists every attempt, failed ones included | Patch the browser queue and the response schema |
| #188 misleading Cancel | Don't build a Cancel without server-side cancellation | Relabel now |
| #190 T&E errors | Backend fix (PR #203) applies to both |
