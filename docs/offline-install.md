# Offline install (Ubuntu 24.04, no internet)

This is the procedure for installing the platform on a machine with no network access (#60). It covers the API, both front ends (the React app, still the default, and the Streamlit app that replaces it in #257), PostgreSQL 16 and the T&E schema.

**Windows, macOS, or an Ubuntu machine you would rather not install packages on?** Use the [container bundle](#container-bundle-windows-macos-and-linux-128) instead: the same platform as three containers, installed with Docker or Podman.

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
| `wheels/` | Python wheels for CPython 3.12 on x86_64 Linux: everything in `api/requirements.txt` and `streamlit_app/requirements.txt`, plus pip |
| `frontend/` | The React frontend, prebuilt to run under Node.js |
| `debs/` | Ubuntu 24.04 packages for PostgreSQL 16, `python3.12-venv` and Node.js 18, with dependencies, plus an index so apt can use the folder as a repository |
| `SHA256SUMS` | A checksum for every file in the bundle |

The bundle was about 140 MB with the React frontend alone. The Streamlit wheels add about 116 MB (measured in `DECISIONS/2026-11-16-streamlit-migration-plan.md`, accepted by the owner on 24 Nov), so expect roughly 260 MB. The real figure is printed at the end of `build_bundle.sh`. The Streamlit app's source travels in `app/streamlit_app/`.

## 1. Build the bundle (connected machine)

You need Ubuntu 24.04 x86_64 with `git`, `python3-pip`, Node.js 22.12 or later and `apt-utils`. WSL Ubuntu 24.04 on Windows works. It must be 24.04, not a newer release, because the Ubuntu packages are downloaded from the build machine's own sources.

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
4. Deploys database `te_mgmt_prod` with schema `te_prod` and its owner role `te_prod_user`. It also creates the runtime role `te_prod_runtime`, which serves requests and can only read and insert the audit and upload tables (M3d, #107). Both get generated passwords.
5. Writes `/opt/te-migration/env` (mode 600) with both passwords, and starts three services under systemd. There is no shared API key (#298): people and scripts sign in.

   | Service | Port | What it is |
   |---|---|---|
   | `te-api` | 8000 | The API |
   | `te-frontend` | 3000 | The React app, still the default front end until the cutover (#257) |
   | `te-streamlit` | 8501 | The Streamlit app (#256). It runs from its own virtual environment (`/opt/te-migration/streamlit-venv`) and reads `/opt/te-migration/streamlit.env` (mode 600), which holds only `API_URL=http://localhost:8000` and `MAX_UPLOAD_BYTES`, no database password. It calls the API from the server, so `localhost` is right whatever address you passed. It starts in `app/streamlit_app/`, so Streamlit reads the shipped `.streamlit/config.toml`, which switches usage statistics off (`browser.gatherUsageStats = false`) |

   `MAX_UPLOAD_BYTES` (default 52428800, 50 MiB) is written to both env files, so the API and the Streamlit app refuse the same files. To change it, set it on the `sudo` line like the variables above. Streamlit's own limit, `server.maxUploadSize` in `config.toml`, must stay above it (it is 53 MB).
6. Creates the first tenant and its tenant admin, then runs the smoke test.

During step 2, apt may print `W: Download is performed unsandboxed as root`. This only means apt's sandbox user can't read the bundle folder, and it's harmless.

## 4. Verify

The install finishes by printing these eight lines. Every one must read PASS:

```
PASS  API health
PASS  API rejects a request without a session
PASS  admin signs in
PASS  session is tenant_admin
PASS  upload a CSV (2 rows inserted)
PASS  upload listed with persisted counts
PASS  frontend serves the app
PASS  Streamlit app health
```

The last line is Streamlit's own health endpoint, `http://localhost:8501/_stcore/health`, answering `ok`.

The upload and listing checks sign in as the first tenant admin.

Then open `http://<API_HOST>:3000` in a browser. You should land on the sign-in page. Sign in with the tenant, username and password from `/root/te-initial-admin`, or the values you set.

The Streamlit app is at `http://<API_HOST>:8501`, with the same sign-in. A session in one app does not carry over to the other: each keeps its own.

You can re-run the check at any time:

```bash
cd /opt/te-migration
sudo env SMOKE_TENANT=main SMOKE_USER=admin SMOKE_PASSWORD='<the admin password>' \
  bash app/scripts/offline/smoke_test.sh
```

Without `SMOKE_TENANT`, `SMOKE_USER` and `SMOKE_PASSWORD` the sign-in, upload and listing checks cannot run, so it reports them as a FAIL and exits non-zero. Use the tenant and username the install used (in `/root/te-initial-admin`).

## Evidence for #60

Attach the following to #60:

1. `~/install.log` from step 3, showing all eight PASS lines.
2. Proof that the VM has no outside network. This command should print `000` or a connection error:
   ```bash
   cd ~
   ip route; curl -s -m 5 -o /dev/null -w '%{http_code}\n' https://pypi.org
   ```
3. The commit in the bundle name, the VM's `lsb_release -d`, and the date.
4. For the Streamlit app (#256): that with telemetry off it makes no outside connection. Usage statistics are off in the shipped `config.toml`, but that this means no outside connection **has not been tested**. With the VM still offline, open the Streamlit app in a browser, sign in and open each page, then check that `te-streamlit` tried nothing outside the machine, for example:
   ```bash
   sudo journalctl -u te-streamlit --no-pager | grep -iE 'connect|resolve|timeout' || echo "no outbound attempts logged"
   sudo ss -tnp | grep -v -E '127\.0\.0\.1|::1' | grep python || echo "no non-local connections from Python"
   ```
   Run the `ss` line while the pages are open. A firewall log on the VM's host, if you have one, is stronger evidence than either.

Once that evidence is on #60, the README can move to the "fully offline" wording in `DECISIONS/2026-10-04-sovereignty-wording.md`.

## Known limits

- **Fresh VM only.** Re-running `install.sh` replaces `/opt/te-migration`. The database script has only been run against an empty database.
- **Change the first admin's password.** The installer generates it. Sign in and change it with the key icon in the header. If it's lost, reset it on the VM (bash, as root). This is the same way the installer runs its admin script:
  ```bash
  cd /opt/te-migration/app
  sudo bash -c 'set -a; . /opt/te-migration/env; set +a; runuser -u te-app -- /opt/te-migration/venv/bin/python scripts/reset_password.py --username admin'
  ```
- **The API address is fixed at install** for the React app: it's written into the frontend files. To change it, re-run the install. The Streamlit app does not need it (it calls the API on `localhost`).
- **Two front ends until #257.** Both run; React is the default. The cutover and the removal of `te-frontend` and Node.js are #257.
- **Ubuntu 24.04 x86_64 only.** Other operating systems need different packages and wheels. An offline container bundle for Windows, macOS and Linux is tracked as #128 (BR-38).

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

## Container bundle (Windows, macOS and Linux, #128)

BR-38: the platform installs and runs with no internet access on any Windows, macOS or Linux host that has Docker or Podman. It is three containers instead of packages on the host.

| Image | What it is |
|---|---|
| `te-api` | The FastAPI backend (Python 3.12). Port 8000 |
| `te-frontend` | The web app (Node.js 22, the Nitro server build). Port 8080 |
| `te-db` | PostgreSQL 16. On its first start it deploys the T&E schema and creates the application roles |

Use this bundle when the host is Windows or macOS, or when you want nothing installed on the host but a container runtime. The Ubuntu procedure above installs natively and is unchanged.

### What you need on the offline machine

- **Docker** (Docker Desktop, or Docker Engine with the Compose plugin) **or Podman**. Docker Desktop needs a paid subscription for larger organisations; Podman is free.
- Linux containers. On Windows, Docker Desktop must be in Linux-container mode (its default).
- Podman also needs a compose provider (`podman-compose`, or `docker-compose` with Podman's API socket running) and its default networking (`netavark` and `aardvark-dns`, which an ordinary Podman install includes).
- About 2 GB of free disk space for the images, and ports 8000 and 8080 free.
- Nothing else. The installer needs no internet access and does not pull anything.

### 1. Get the bundle (connected machine)

CI builds it: download the `te-container-bundle` artifact from the **Container bundle** workflow run. It holds the images for **amd64** (Intel and AMD) and **arm64** (Apple Silicon, Windows on Arm), and the installer picks the one that matches the machine.

To build it yourself, with Docker or Podman and internet access, once on each CPU type you want to support:

```bash
bash container/build_bundle.sh images                       # builds the three images, saves dist/te-images-<version>-<cpu>.tar
bash container/build_bundle.sh assemble dist/te-images-*.tar  # one or more tarballs, one per CPU -> dist/te-container-bundle-<version>.tar.gz
```

`TE_RUNTIME=podman` builds with Podman. The `.tar.gz` has a `.sha256` file next to it.

**Software bill of materials (#326).** The bundle CI builds holds a CycloneDX SBOM for each image of each CPU, six files in `sbom/` (`te-api-amd64.cdx.json` and so on), listed in `SHA256SUMS` and checked by the installer with everything else. They list every operating-system package and every Python and Node.js package in the image, so a customer can assess or accredit the components. CI writes them with [trivy](https://trivy.dev), and the **Container bundle** workflow also scans each image for known vulnerabilities: a fixable HIGH or CRITICAL finding fails the job, and no bundle is assembled. Accepted exceptions are in `.trivyignore.yaml`, each with a reason and an expiry date. A bundle you assemble yourself has an `sbom/` folder only if you put the SBOMs in `dist/sbom/` first (`TE_REQUIRE_SBOM=1` makes a missing one an error).

### 2. Move it to the offline machine

Copy the `.tar.gz` and its `.sha256`, check the checksum, and extract:

```bash
sha256sum -c te-container-bundle-<version>.tar.gz.sha256     # macOS: shasum -a 256 -c
tar -xzf te-container-bundle-<version>.tar.gz
cd te-container-bundle-<version>
```

On Windows, check it with `Get-FileHash <file> -Algorithm SHA256` and extract with `tar -xzf` (built in) or 7-Zip. The installer also verifies every file inside the bundle (`SHA256SUMS`) before it does anything.

### 3. Install

| Host | Command, from inside the extracted folder |
|---|---|
| macOS, Linux | `bash install.sh` |
| Windows | `powershell -ExecutionPolicy Bypass -File .\install.ps1` |

Add the name or address people will use to reach this machine if it is not just this machine (for example `bash install.sh intranet-host`, or `-TeHost intranet-host` on Windows). The default, `localhost`, works only from the machine itself.

Optional environment variables: `TE_RUNTIME` (`docker` or `podman`; default: whichever is installed, Docker first), `TE_TENANT` (default `main`), `TE_ADMIN_USER` (default `admin`), `TE_ADMIN_PASSWORD` (12+ characters; default: generated).

The installer, in order:

1. checks every file against `SHA256SUMS`;
2. loads the images for this machine's CPU from the bundle (no download);
3. generates the secrets into `.env` (readable only by you; never in an image);
4. starts the database, API and web app, and waits until the API answers;
5. creates the first tenant admin, once. A generated password is written to `te-initial-admin` (readable only by you): change it after first sign-in;
6. runs the smoke test (below) and checks ports 8000 and 8080 answer on the host.

Then open `http://localhost:8080` and sign in with the tenant and admin it printed.

It is safe to run again: the secrets and data are kept, and the admin is not created a second time. Run it with a different host name to change the address the web app uses.

### 4. Verify

The installer's last step is the smoke test, `container/smoke_test.py`, which runs inside the API container so that it needs nothing on the host. It is the Ubuntu install's checks without the Streamlit one (the container bundle has no Streamlit container yet; #256 packaged it for the Ubuntu bundle and Azure), and prints `7 of 7 passed`:

1. API health
2. the API rejects a request with no key
3. a CSV uploads (2 rows inserted)
4. the upload is listed with its persisted counts
5. the web app serves its page
6. the admin signs in
7. the session is a tenant admin

### Everyday operation

```bash
docker compose down        # stop. Your data is kept in the te-db volume
docker compose up -d       # start again
docker compose logs api    # look at a problem (use `podman compose` with Podman)
docker compose down -v     # stop AND delete the database. This cannot be undone
```

**Keep `.env` with the data.** The database is created once, with the secrets in `.env`; they cannot be regenerated for an existing database. If you extract a newer bundle into a new folder, copy the old folder's `.env` (and `te-initial-admin`, if you still need it) into it before you run `install.sh`. Backups and upgrades across versions are not covered here yet.

### If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `neither docker nor podman is installed`, or `... is installed but not running` | Install or start the runtime (Docker Desktop, or `podman machine start`) |
| `checksum mismatch` | The bundle is damaged or incomplete: copy it again |
| `a database volume (te_te-db) from an earlier install exists, but this folder has no .env` | The data outlives the folder. The secrets it was created with are in the old folder's `.env`: copy that file here and run again to keep the data. To start from nothing, **deleting the data**, run again with `TE_RESET=1` |
| `this bundle has no images for <cpu>` | The bundle was built without that CPU. Rebuild with `assemble` given a tarball for it |
| Port 8000 or 8080 already in use | Stop what is using it. The ports are fixed in `container/docker-compose.yml` |
| `the API did not become healthy in 4 minutes` | Run `compose logs`. The usual cause is a port or disk problem |
| Podman: `failed to connect to the docker API` | `podman compose` chose `docker-compose` and Podman's API socket is not running. Start it (`systemctl --user enable --now podman.socket`) or install `podman-compose` |
| Podman: the API never turns healthy | Podman runs healthchecks from systemd timers, so a host without systemd shows `starting` forever |

### What is proved, and where

The offline test is: start from a machine with no images, with the containers cut off from the internet at the firewall, install from the extracted bundle, and pass the smoke test.

| Host and runtime | Status |
|---|---|
| Linux amd64, Docker | **Passed**, 7 of 7, by hand and in CI. The Container bundle workflow repeats it on every change. The bundle CI built (both CPUs, about 550 MB) was also downloaded and installed by hand with the containers cut off: 7 of 7 |
| Linux amd64, Podman with `podman-compose` | **Passed**, 7 of 7, by hand (Podman 4.9) and in CI |
| Linux amd64, Podman 4.9 with `docker-compose` over its API socket | **Passed**, 7 of 7 (healthcheck timer emulated; the host had no systemd) |
| Linux arm64, Docker | **Passed** in CI, 7 of 7, on a native arm64 runner (no emulation). Not run by hand |
| `install.ps1` | **Passed**, 7 of 7, under PowerShell 7.4 on Linux against Docker. **Not yet run on Windows** |
| Windows, Docker Desktop or Podman | **Not yet run.** Needed for BR-38 |
| macOS (Apple Silicon), Docker Desktop or Podman | **Not yet run.** Needed for BR-38 |

BR-38 is done when the smoke test passes 7 of 7 with networking off on Windows, macOS and Linux. Attach, for each: the installer's output, how you proved the network was off, the OS and runtime versions, and the bundle's version. The run sheet, with the commands and the evidence table, is `docs/BR38_EVIDENCE.md`.

### Known limits

- No TLS: the web app and API are plain HTTP, as in the Ubuntu install. Put a reverse proxy in front for anything beyond a private network.
- Windows containers are not supported; the images are Linux images.
- The first tenant admin's password is written to a file the first time. Change it after signing in, and delete the file.
- The installer has been run under PowerShell 7, not yet under Windows PowerShell 5.1, which it is written to support.
