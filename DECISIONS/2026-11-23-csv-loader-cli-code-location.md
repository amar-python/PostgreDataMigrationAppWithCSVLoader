# Decision: The CSV-loader command-line tool's code lives in this repository (#382)

Status:  Decided by the owner on 2026-11-23 (comment on #363); recorded here 2026-11-24. The code is not imported yet, so nothing below is done
Date:    2026-11-23
Review:  When the import PR merges (to confirm the folder name, the test layout and the CI jobs), or 2026-12-07 if it has not been opened by then
Changes: nothing. Adds to `2026-10-04-repo-consolidation.md` (`te-csv-migration` stays archived)

## Choice

The standalone CSV-loader tool (`main.py`, `config.yaml`, `auto_migrate.py`, `src/`, its tests, `requirements.txt`, `Dockerfile`, `.dockerignore`) is brought into `PostgreDataMigrationAppWithCSVLoader`, in its own top-level folder. Issues #347 to #362 (CLI-01 to CLI-16) stay open here and are fixed by pull requests here.

Chosen by the owner on 23 Nov from three options in #382:

- **Bring the tool in** (this)
- Move #347 to #362 to the repository that holds the code, and close them here
- Close them as not applicable

## Context

- The CLI audit of 23 Nov produced 16 findings and a tracker (#363). The audited files are not in this repository, on `main` or in its history: the report says they sit in the owner's home folder beside the T&E app.
- `te-csv-migration` is a different, archived project, so it is not the home for this code.
- Until the code is here, the file:line references in #347 to #362 cannot be checked, and 15 of the 16 are Medium or High. They sit at the top of the open list and nobody can act on them (#382).
- The audit's evidence is the report as supplied: it ran the tool's 72 unit tests (passing), not its 8 database tests, and did not run the tool against a real PostgreSQL. The watcher finding (CLI-05) is from knowledge of `watchdog`, not from running it.

## Reasoning

- One repository means one CI, one `scripts/lint.sh` (it lints every tracked Python file since #344), one security review and one issue list. The tool and the T&E app are used together.
- The credential risk in CLI-02 (`COPY . .` from a home folder) goes away at the source once the tool has its own folder.
- Moving the issues would split the audit trail, and closing them as not applicable would drop findings, several of which change data while reporting success (CLI-03, CLI-04, CLI-06).

## What this commits us to

1. **The owner gets the code in.** The assistant's session has no access to the owner's computer, so this is the blocking step. Either (a) the owner commits and pushes the app files from the local copy on a branch, or (b) shares the folder through Remote Control, or (c) attaches the files.
2. **Import the application only.** Not the rest of the home folder, and no credentials, cloud logins, `.env` files or downloads. Run `git status` and read the file list before pushing, because CLI-02 is exactly this mistake.
3. **Before the first fix, check CLI-02 against reality.** Was a Docker image ever built or pushed from the home folder? If so, rotate whatever was in that folder. Also rotate the database password typed into the chat on 17 Nov (see `docs/audit/20261123.md`).
4. **Fix order, once the code is in** (from #363): CLI-01 and CLI-02; then CLI-03 and CLI-06, with the two tests from CLI-12 written first; then CLI-04 and CLI-05; then CLI-07 to CLI-10 and CLI-13; then CLI-11; then the cleanup in CLI-14 to CLI-16.

## Still to decide with the import

| Question | Default if the owner does not say | Why it matters |
| --- | --- | --- |
| Folder name | `csv_loader/` (suggested in #363, not confirmed) | Keeps `main.py`, `config.yaml` and `src/` from colliding with this repository's layout |
| Where its tests live | Inside the folder, collected by the existing root `pytest.ini` | CLI-13 (missing `pytest.ini`) is about the tool's old project; this repository already has one |
| CI | The 72 unit tests in the free-tier job; the 8 database tests in the integration job that has PostgreSQL | The DB tests are the ones that cover staging, promotion and `auto_migrate.py` (CLI-12) |
| Overlap with `build/csv/*` | Check, do not assume | See below |

## Overlap with `build/csv/` (not checked by running anything)

This repository already has a CSV validator and loaders (`build/csv/validator.py`, `build/csv/loader_*.sh`). Reading `validator.py` only:

- **CLI-04 (short rows become NULLs):** does not look shared. `validator.py` skips any row whose length differs from the header, in both directions, and writes it to the skip file.
- **CLI-15 (BOM stripped three times):** not shared. `validator.py` opens the file with `utf-8-sig` once.
- **CLI-09 (TSV read as one column):** possibly shared. `validator.py` detects the delimiter and keeps it in the validated file, while `loader_postgresql.sh` hard-codes `DELIMITER ','`. Whether a TSV can reach that loader was not tested.
- **CLI-06 (leading zeros) and CLI-03 (decimal rounding):** not assessable from the validator. Check how the loaders create column types.

If either tool turns out to duplicate the other's job, that is a separate decision (one loader or two). It is not made here.

## What it costs

- The repository gets a second application, with its own dependencies and Dockerfile. The SE-series gaps (no type checking, unpinned dependencies, no single Python version: #323, #327, #328) apply to it as well.
- 16 findings, 15 of them Medium or High, stay on the open list until the code arrives. The count only falls once the import is merged.

## Done when

- The tool's code is on `main` under its own folder, with tests collected by CI and the import PR's file list reviewed for credentials.
- Each of #347 to #362 is either reproduced and fixed by a pull request, or closed with the reason (for example, already fixed in the tool, or not reproducible).
- #382 is closed with a link to this file.
