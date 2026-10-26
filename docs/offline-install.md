# Offline install (Ubuntu 24.04, no internet)

This is the procedure for installing the platform on a machine with no network access (#60). It covers the API, the frontend, PostgreSQL 16 and the T&E schema.

It uses two scripts:

| Script | Runs on | Does |
|---|---|---|
| `scripts/offline/build_bundle.sh` | A **connected** Ubuntu 24.04 x86_64 machine | Builds one `.tar.gz` holding everything the offline machine needs |
| `scripts/offline/install.sh` | The **offline** Ubuntu 24.04 x86_64 VM | Installs from that file alone, then runs `smoke_test.sh` |

**Status:** rehearsed here with networking switched off, but not yet run on a clean VM. That VM run is the evidence #60 needs (see [Evidence for #60](#evidence-for-60)).

## What the bundle contains

| Part | Contents |
|---|---|
| `app/` | The repository at the bundle's commit, without the frontend source |
| `wheels/` | Python wheels for CPython 3.12 on x86_64 Linux: everything in `api/requirements.txt`, plus pip |
| `frontend/` | The frontend, prebuilt to run under Node.js |
| `debs/` | Ubuntu 24.04 packages for PostgreSQL 16, `python3.12-venv` and Node.js 18, with dependencies, plus an index so apt can use the folder as a repository |
| `SHA256SUMS` | A checksum for every file in the bundle |

The bundle is about 140 MB.

## 1. Build the bundle (connected machine)

You need Ubuntu 24.04 x86_64 with `git`, `python3-pip`, Node.js 20 or later and `apt-utils`. WSL Ubuntu 24.04 on Windows works.

```bash
cd ~/PostgreDataMigrationAppWithCSVLoader
git checkout main && git pull
bash scripts/offline/build_bundle.sh
```

This produces two files, `dist/offline-bundle-<commit>.tar.gz` and `dist/offline-bundle-<commit>.tar.gz.sha256`.

## 2. Move it to the offline VM

Copy both files by your approved transfer method. Then, on the VM, check that the bundle arrived intact and unpack it:

```bash
cd ~
sha256sum -c offline-bundle-<commit>.tar.gz.sha256
tar -xzf offline-bundle-<commit>.tar.gz
```

## 3. Install (offline VM)

```bash
cd ~/offline-bundle-<commit>
sudo bash app/scripts/offline/install.sh localhost 2>&1 | tee ~/install.log
```

The argument is the address browsers use to reach the API. Use `localhost` when the browser runs on the VM itself; otherwise use the VM's hostname or IP address.

The first tenant and its admin come from three optional variables, set before `sudo` with `sudo -E` or on the same line:

| Variable | Default |
|---|---|
| `TE_TENANT` | `main` |
| `TE_ADMIN_USER` | `admin` |
| `TE_ADMIN_PASSWORD` | Generated and written to `/root/te-initial-admin` (mode 600, root only). It is not printed, so it stays out of `install.log`. |

The script runs six steps:
1. Checks every file against `SHA256SUMS`.
2. Installs the Ubuntu packages, using the bundle as the only apt source. The VM's own apt sources are ignored.
3. Copies the app to `/opt/te-migration`, creates the `te-app` system user, and builds a Python virtual environment from `wheels/` without network access.
4. Deploys database `te_mgmt_prod` with schema `te_prod` and its login role `te_prod_user`, using a generated password.
5. Writes `/opt/te-migration/env` (mode 600) with that password and a generated API key, and starts the `te-api` (port 8000) and `te-frontend` (port 3000) services under systemd. The API key is for scripts only. The frontend holds no key; people sign in.
6. Creates the first tenant and its tenant admin, then runs the smoke test.

During step 2, apt may print `W: Download is performed unsandboxed as root`. This only means apt's sandbox user can't read the bundle folder, and it's harmless.

## 4. Verify

The install finishes by printing these seven lines. Every one must read PASS:

```
PASS  API health
PASS  API rejects a missing key
PASS  upload a CSV (2 rows inserted)
PASS  upload listed with persisted counts
PASS  frontend serves the app
PASS  admin signs in
PASS  session is tenant_admin
```

Then open `http://<API_HOST>:3000` in a browser. You should land on the sign-in page. Sign in with the tenant, username and password from `/root/te-initial-admin`, or the values you set.

You can re-run the check at any time:

```bash
cd /opt/te-migration
sudo bash app/scripts/offline/smoke_test.sh "$(sudo sed -n 's/^API_KEY=//p' env)"
```

## Evidence for #60

Attach the following to #60:

1. `~/install.log` from step 3, showing all seven PASS lines.
2. Proof that the VM has no outside network. This command should print `000` or a connection error:
   ```bash
   cd ~
   ip route; curl -s -m 5 -o /dev/null -w '%{http_code}\n' https://pypi.org
   ```
3. The commit in the bundle name, the VM's `lsb_release -d`, and the date.

Once that evidence is on #60, the README can move to the "fully offline" wording in `DECISIONS/2026-10-04-sovereignty-wording.md`.

## Known limits

- **Fresh VM only.** Re-running `install.sh` replaces `/opt/te-migration`. The database script has only been run against an empty database.
- **Change the first admin's password.** The installer generates it. There's no self-service password change yet, so rerun `scripts/create_tenant_admin.py` for a new admin if needed.
- **The API address is fixed at install.** It's written into the frontend files. To change it, re-run the install.
- **Ubuntu 24.04 x86_64 only.** Other operating systems need different packages and wheels.

## How it was rehearsed

### Second rehearsal (26 Oct 2026, with frontend sign-in, #96)

The second rehearsal ran the same way as the first: inside a network namespace with only a loopback interface, where `curl https://pypi.org` returned `000`.

- **Install:** `install.sh` ran end to end. The first admin was created in tenant `main`, and `/root/te-initial-admin` was mode 600, owned by root.
- **Smoke test:** the in-install run had 6 of 7 pass. The frontend check ran before Node had finished starting, because the test only waited for the API. The smoke test now waits for both. Rerun against the same install, it passed **7 of 7**.
- **Browser (Playwright, inside the same namespace):**
  - signed out, both `/` and `/audit` land on `/auth`;
  - a wrong password shows the generic error;
  - signing in reaches the upload page, with the header showing `admin · main` (role `tenant_admin`);
  - the page contains no API key, and the token is in `sessionStorage`;
  - signing out returns to `/auth`, and `/` redirects there again.
- **Upload through the UI:** every API call carried `Authorization: Bearer` and none carried `X-API-Key`. The file landed in `tenant_main.csv_files` with 2 rows.

### First rehearsal (26 Oct 2026)

The rehearsal ran in Claude's Ubuntu 24.04 workspace, inside a Linux network namespace that had only a loopback interface. `curl https://pypi.org` returned `000` from inside it.

- **What ran:** `install.sh` end to end. Checksums verified (468 files), packages installed from the bundle's local repository, the venv built from wheels, `te_mgmt_prod` deployed with 12 T&E tables, both services started, and the smoke test passed 5 of 5. The smoke test then passed twice more against the running install.
- **What differed from a real VM:**
  - systemd was replaced by a stand-in that starts each unit's `ExecStart` as its `User`.
  - PostgreSQL 16 was already installed in the workspace, so only Node.js was newly installed from the bundle.

These differences are why the clean-VM run is still needed.
