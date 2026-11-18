# BR-38 evidence checklist (#128)

BR-38 is done when the container bundle's smoke test passes **7 of 7 with networking off** on Windows, macOS and Linux (`docs/VCRM.md`). This is the run sheet for the part still open. Linux is proved: #245 added the bundle, and its CI run installed it with the containers cut off from the internet on amd64 and arm64 with Docker, and on amd64 with Podman. See "What is proved, and where" in `docs/offline-install.md`.

**What was and was not run.** The Windows and macOS commands below were written for this checklist and have **not** been run on those systems. Only the network probe (step 3) was run, on Linux, where it exits 0 with the network open and 1 with it blocked. If a command here is wrong on your machine, say so in the evidence; do not work around it silently.

## Runs

| # | Host | Needed for BR-38 |
|---|---|---|
| 1 | Windows 10 or 11, Docker Desktop (Linux containers) or Podman, `powershell -ExecutionPolicy Bypass -File .\install.ps1` (this starts Windows PowerShell 5.1, the version the script targets) | **Yes** |
| 2 | macOS (Apple Silicon), Docker Desktop or Podman, `/bin/bash install.sh` (macOS's own bash 3.2, the version the script targets) | **Yes** |
| 3 | Windows with PowerShell 7 (`pwsh`), or Windows on Arm | No. Closes a gap listed in `docs/offline-install.md` |
| 4 | Linux arm64 by hand | No. CI already ran it on a native arm64 runner |

## A run counts only if

1. **The bundle is CI's.** The `te-container-bundle` artifact of a **Container bundle** workflow run on `main`, with its `.sha256` matched.
2. **It starts from nothing.** No `te-*` images and no `te_te-db` volume on the machine.
3. **The network is proved off from inside a container**, not from the Wi-Fi toggle. Step 3 does this.
4. **The installer's whole output ends** `7 of 7 passed`, then `PASS  ports 8000 and 8080 answer on this machine`, then `Installed.`
5. **Nothing was downloaded.** The network stayed off from step 3 to the end.

## Steps on Windows (PowerShell)

Every block starts with `cd`. Replace the quoted paths and `<version>` (the bundle's short commit hash, in its file name). Use `podman` for `docker` throughout if the machine runs Podman, and `localhost/te-api` for `te-api` in step 3.

**1. Record the versions** (they are part of the evidence):

```powershell
cd "C:\path\to\the\download"
$PSVersionTable.PSVersion
[System.Environment]::OSVersion.VersionString
docker version
```

**2. Check the bundle, extract it, start from nothing:**

```powershell
cd "C:\path\to\the\download"
(Get-FileHash .\te-container-bundle-<version>.tar.gz -Algorithm SHA256).Hash.ToLower()
Get-Content .\te-container-bundle-<version>.tar.gz.sha256
tar -xzf .\te-container-bundle-<version>.tar.gz
docker image ls "te-*"
docker volume ls --filter name=te_te-db
```

The two hashes must be equal. The last two commands must list nothing. If they list something, remove it (`docker compose down -v`, then `docker image rm` each `te-*` image) and start again.

**3. Turn the network off, then prove it.** Disconnect Wi-Fi and unplug any cable. Load the images, then try to reach the internet from a container:

```powershell
cd "C:\path\to\the\download\te-container-bundle-<version>"
docker load -i images-amd64.tar
$v = (Get-Content .\VERSION).Trim()
docker run --rm --entrypoint python "te-api:$v" -c "import socket; socket.create_connection(('1.1.1.1', 443), 5)"
$LASTEXITCODE
```

Use `images-arm64.tar` on Windows on Arm. The probe must print a traceback ending in an `OSError` (for example `TimeoutError`, `Network is unreachable` or `ConnectionRefusedError`) and `$LASTEXITCODE` must be `1`. **If it prints `0`, the network is still up: stop, the run does not count.**

**4. Install.** Copy the **whole** console output into the evidence:

```powershell
cd "C:\path\to\the\download\te-container-bundle-<version>"
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

**5. Show the state, then run the installer again.** The second run must print `already installed; keeping the existing admin` and finish `7 of 7 passed`:

```powershell
cd "C:\path\to\the\download\te-container-bundle-<version>"
docker compose ps
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

**6. Clean up** (deletes the test data):

```powershell
cd "C:\path\to\the\download\te-container-bundle-<version>"
docker compose down -v
Remove-Item .\te-initial-admin
```

## Steps on macOS (bash)

Replace the quoted paths and `<version>`. Use `podman` for `docker` if the machine runs Podman, and `localhost/te-api` for `te-api` in step 3.

**1. Record the versions:**

```bash
cd "/path/to/the/download"
sw_vers; uname -m; /bin/bash --version | head -1; docker version
```

**2. Check the bundle, extract it, start from nothing:**

```bash
cd "/path/to/the/download"
shasum -a 256 te-container-bundle-<version>.tar.gz
cat te-container-bundle-<version>.tar.gz.sha256
tar -xzf te-container-bundle-<version>.tar.gz
docker image ls "te-*"; docker volume ls --filter name=te_te-db
```

The two hashes must be equal and the last two commands must list nothing.

**3. Turn the network off (Wi-Fi off, cables out), then prove it:**

```bash
cd "/path/to/the/download/te-container-bundle-<version>"
docker load -i images-arm64.tar
docker run --rm --entrypoint python "te-api:$(cat VERSION)" -c "import socket; socket.create_connection(('1.1.1.1', 443), 5)"; echo "exit=$?"
```

Use `images-amd64.tar` on an Intel Mac. The probe must end in an `OSError` and `exit=1`. **`exit=0` means the network is up: the run does not count.**

**4. Install** (copy the whole output), **5. check and run again**, **6. clean up:**

```bash
cd "/path/to/the/download/te-container-bundle-<version>"
/bin/bash install.sh
docker compose ps
/bin/bash install.sh
docker compose down -v && rm te-initial-admin
```

## Evidence to post

One comment on #128 per run. **Never paste `.env` or `te-initial-admin`** (they hold secrets).

| Item | Value |
|---|---|
| Run (1 to 4 above), date, who ran it | |
| OS and version, CPU | |
| Runtime and version (`docker version` or `podman version`) | |
| Shell and version (`$PSVersionTable.PSVersion`, or `bash --version`) | |
| Bundle: version, the CI run it came from, the two hashes match (yes or no) | |
| How the network was turned off, and the probe's last line and exit code | |
| `docker image ls "te-*"` and the volume list before step 3 (both empty) | |
| The installer's whole output (step 4) | |
| `docker compose ps` and the second run's output (step 5) | |
| Anything that failed, was skipped or was done differently from this sheet | |

## When it is done

1. Rows 1 and 2 are posted and each shows `7 of 7 passed` with a valid probe. Then update the two "Not yet run" rows in `docs/offline-install.md` and the BR-38 row in `docs/VCRM.md`, each linking the evidence, and close #128 (its **Done when** is this evidence).
2. A run that fails is a bug, not a retry: open an issue from the template in `docs/WRITING.md` with the output attached.
3. Do not describe the install as "fully offline" until #60 has its evidence (`docs/WRITING.md`).
