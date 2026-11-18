# Streamlit front end (migration step 1: the app shell, #251)

Part of the plan in `DECISIONS/2026-11-16-streamlit-migration-plan.md` (#212). **The React app in
`csv-table-hub-main/` is still the live front end.** This app is not wired into the Docker image or the
offline bundle yet; that is step 5 (#256). The unit tests and the accessibility scans do cover it in CI.

Screens: sign-in, change password, a home page that says what the signed-in role can do, Review (#252),
Import history (#253) and Upload (#255). Later screens appear only for roles that can use them.

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

`MAX_UPLOAD_BYTES` (default 52428800, 50 MB) is the largest CSV the Upload screen accepts. **Set it to the
same value for the app and the API**, or a file one side accepts is refused by the other.

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

## Tests

- `tests/unit/test_streamlit_*.py`: fast, headless (Streamlit's `AppTest`, a faked API). Run with
  the unit tests in CI.
- `tests/accessibility/`: axe scans of the Streamlit screens, in the CI accessibility job.
- `e2e/test_streamlit_shell.py`: one browser test that sign-out leaves nothing for the next tenant. Run
  like the other end-to-end tests (`e2e/README.md`); not part of CI.
