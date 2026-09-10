# Reconciled Gap Register — O-01 to O-12

**Baseline:** `C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader`, branch `main` @ `269ffe2`
**Date:** 2026-09-10
**Method:** every status below was verified by reading the code or executing it in this repo. No status is carried over from a document claim alone.

---

## Correction to the previous version of this register

An earlier draft of this document concluded that "Abacus reviewed a superseded API design." **That conclusion was wrong**, and it was wrong for an instructive reason.

That draft was built from a package snapshot (`PostgreDataMigrationAppupdate.7z`) rather than from this repository. Inside that snapshot, `api-for-github.zip` contains a *thin-translator* API — a single `api/main.py` that shells out to `build/csv_loader.sh`, with no `config.py`, no `db.py`, no `routers/`, no `services/`. Finding that, the draft inferred the routers/services architecture Abacus described had been replaced.

The live repository tells a different story. It has `api/config.py`, `api/db.py`, `api/routers/{csv,te,audit}_routes.py` and `api/services/{csv_parse,dynamic_loader,te_loader}.py` — the architecture Abacus actually reviewed. The thin translator in that zip is a **separate parallel artifact**, not the successor to this code.

Two lessons worth keeping:

1. **A snapshot is not the repository.** The 7z was a partial delta — it did not contain `build/config.env.example`, `build/setup.sh`, the six `build/csv/loader_*.sh` scripts, `tests/suites/`, or `build/adapters/`. Those absences are precisely what made the highest-priority gaps look unfixable, and what made a wrong architectural inference possible.
2. **Confirm the baseline before reviewing.** Reviewing the wrong artifact produced a register that was confidently, specifically incorrect across ten rows.

Abacus's real limitation was different and narrower: it reviewed an **older commit**. The repository has since addressed BUG-006, 025, 027, 028, 030, 031, 035, 040 and 041, added `api/auth.py` and `api/routers/audit_routes.py`, and resolved GAP_ANALYSIS G1, G4 and G5.

---

## Status of O-01 to O-12

| ID | Gap | Status | Evidence |
|----|-----|--------|----------|
| O-01 | `config.env.example` names mismatch loaders/`setup.sh` | ✅ **Already closed** | GAP_ANALYSIS G1, resolved 2026-08-12. Verified: `config.env.example` and `setup.sh` both use the `PG_*_<ENV>` scheme. |
| O-02 | BR-15 `conn_limit` not asserted | ✅ **Already closed** | Assertion **S10** in `tests/suites/test_05_schema_and_business_rules.sql` reads `pg_roles.rolconnlimit`. |
| O-03 | No auth fail-closed, no rate limiting | ✅ **Fixed this pass** | `API_ENV` gate + `api/ratelimit.py`. 24 tests in `tests/test_api_hardening.py`. |
| O-04 | `audit_log` written on delete only | ✅ **Fixed this pass** | `api/services/audit.py`; upload path audited; delete refactored onto the shared writer. |
| O-05 | No migration-history endpoint | ✅ **Already closed** | `GET /api/csv/files` in `csv_routes.py`; pagination added in `269ffe2`. |
| O-06 | No dedup layer | ✅ **Already closed** | Three levels in `dynamic_loader.py`: filename, content SHA-256, per-row `_row_hash UNIQUE`. |
| O-07 | BR-01 cross-env parity unverified | ✅ **Fixed this pass** | Tier E scenario `01_envs_have_identical_structure` + 10 unit tests + CI wiring. |
| O-08 | BR-02 non-PG engines unverified | ⏸ **Measured, then deferred by decision** | Tier X scenario `01_sqlite_schema_structure` measured the shortfall; [ADR-0001](adr/0001-postgresql-first.md) defers multi-engine until the PostgreSQL milestone. |
| O-09 | Windows CI cannot host PostgreSQL | ✅ **Accepted + improved** | GAP_ANALYSIS G2 accepted. Tier X now runs there — the first cross-engine coverage that job has ever carried. |
| O-10 | Runtime artifacts not gitignored | ✅ **Already closed** | GAP_ANALYSIS G4, resolved 2026-08-13. Verified: all four entries present, plus `evals/reports/`. |
| O-11 | VCRM BR-20 count edited 85 → 142 | ✅ **Already closed** | GAP_ANALYSIS G5. Confirmed at 142, matching the Tier S expectation JSON. |
| O-12 | Frontend not independently audited | ✅ **Documented this pass** | "Coverage note — frontend" in `docs/VCRM_GAPS.md`, naming two specific risks and the cheapest remedy. |

**Six of the twelve were already closed before this pass began.** They were listed as open because the earlier register was built from the snapshot, not the repo.

---

## O-08 — measured, then deferred by decision

**Settled 2026-09-10.** [ADR-0001](adr/0001-postgresql-first.md) records the
decision: reach a working PostgreSQL milestone first, then apply what that teaches
to the other engines. There is no longer an open decision here. The measurements
below are what made the decision possible.

Building Tier X measured what each engine's `te_core_schema.sql` actually defines:

| Engine | Tables | Against PostgreSQL's 12 |
|---|---|---|
| postgresql | 12 | reference |
| sqlite | 7 | 5 missing |
| mariadb | 7 | 5 missing |
| teradata | 1 | 11 missing |
| influxdb | no DDL (seed `.lp` only) | n/a |
| redis | no DDL (seed `.sh` only) | n/a |

Absent from both SQLite and MariaDB: `temp_documents`, `test_phases`, `test_events`, `test_results`, `evidence_artifacts`.

Those five are the execution and evidence half of the model. What remains is the planning half — organisations, personnel, programs, requirements, test cases, VCRM entries, defects. So both engines can hold a test *plan* and its traceability, but not a record of test *execution*. For a T&E framework that is the material half.

**Why it went unnoticed:** `adapter_<engine>.sh` deploys whatever DDL it is handed and reports success on exit 0. With no cross-engine eval, "the adapter ran" was the only available signal, and it was a true statement about an incomplete schema.

**How it is now recorded:** BR-02's wording in `docs/VCRM.md` is retained unchanged and annotated as deferred by decision — it states the eventual target, not the current milestone. Its status moved from ❌ Not verified to ⏸ Deferred by decision. VCRM coverage is 19 of 22 (86 %) verified with **zero actionable requirement gaps**: the three remaining are all deferred deliberately. Tier X stays in the repository but is out of CI (`make evals-engines` runs it); per-engine open questions are preserved in `docs/ENGINE_PARITY_TODO.md`.

**Why Tier X passes rather than fails:** it pins SQLite's current 7-table baseline instead of asserting 12. Asserting parity would leave the job permanently red for work that is knowingly outstanding, and a job that is always red stops being read. The shortfall is carried instead in `known_missing_tables`, in every generated report's `actual` block, and in the TODO. The scenario still fails on drift in either direction, and `tests/test_evals_tier_e_x.py` asserts the two lists together account for all 12 tables — so the shortfall cannot be understated by omission.

---

## Other findings from this pass

| # | Finding | Action taken |
|---|---------|--------------|
| 1 | Engine parity shortfall (table above) | Measured, then deferred by [ADR-0001](adr/0001-postgresql-first.md). BR-02 annotated as deferred; `docs/ENGINE_PARITY_TODO.md` holds the measured state and open questions |
| 2 | `api/auth.py` docstring claimed "applied globally in api/main.py" — it is applied **per-router**. Enforcement was real, the documentation was not. | Docstring corrected; the per-router rationale (BUG-035, keeping `/api/health` open for probes) now stated where a reader will find it |
| 3 | `scripts/lint.sh` lints a hardcoded file list, so new modules silently escaped flake8 and bandit | Added `api/ratelimit.py`, `api/services/audit.py`, and both new test modules to the list |
| 4 | `docs/VCRM_GAPS.md` was stale: BR-15 had been fixed in code without the traceability document being updated | Updated with status headers and a "what changed" table; coverage restated 77 % → 86 % |
| 5 | `audit_log` had exactly one writer (`delete_file`), so the log recorded destructions but never creations | Fixed under O-04 |
| 6 | Stale git worktree at `.claude/worktrees/velvety-chasing-badger/` holds an older copy of `api/`, including its own `auth.py` and `routers/` | **Not touched** — flagged only. It pollutes repo-wide `grep` results and cost real time during this review. Worth pruning if it is dead. |

---

## Known limitation in the O-04 fix

The loaders own and commit their own transactions, so an upload's audit row is written *after* the load has already committed rather than inside the same transaction. A crash in the narrow window between the two leaves a load with no audit row.

Because of that ordering, a failed audit write does **not** fail the request: the data is already in the database, and reporting failure for a load that actually succeeded would be worse than a missing log line. The failure is logged at ERROR so it is alertable.

Closing that window means threading the caller's connection into the loaders so the audit INSERT joins their transaction. That changes the loader signatures, so it is recorded here rather than smuggled into this pass. The delete path already has the stronger guarantee — it uses `write_audit(cur, ...)` inside its own transaction.

---

## Verification

Everything below was executed in this repo, not asserted from a document.

| Check | Result |
|---|---|
| `pytest -m "unit or regression or security or snapshot"` | **115 passed, 0 failed, 0 skipped** (was 96 before this pass) |
| `scripts/test_report.py --strict` | **RESULT: PASS** — 229 collected, 115 executed, 0 skipped, 114 deselected by marker filter |
| `bash scripts/lint.sh` (flake8 + bandit) | **All lint checks passed**, with the new modules inside the gate |
| `evals/runner.py --tiers p,x` | **24 passed, 0 failed, 0 skipped** |
| `evals/runner.py --tiers e` | Correctly **FAILS** without PostgreSQL, per the repo's no-skip policy (F5) — it does not skip |
| Tier E / Tier X comparison logic | 19 unit tests in `tests/test_evals_tier_e_x.py`, including negative controls for added column, changed type, changed nullability, reordered columns, missing table, extra table |

Tier E's full four-environment comparison has **not** been executed end to end — this session had no PostgreSQL instance. Its comparison logic is unit-tested with negative controls, and the scenario is wired into the `integration-postgres` CI job, so its first real run will be there. That is stated plainly rather than implied as verified.

---

## Files changed

**Added (6)**

```text
api/ratelimit.py
api/services/audit.py
tests/test_api_hardening.py
tests/test_evals_tier_e_x.py
evals/datasets/tier_e/01_envs_have_identical_structure/NOTES.txt
evals/expected/tier_e/01_envs_have_identical_structure.json
evals/datasets/tier_x/01_sqlite_schema_structure/NOTES.txt
evals/expected/tier_x/01_sqlite_schema_structure.json
docs/ENGINE_PARITY_TODO.md
docs/RECONCILED_GAPS.md
docs/adr/0001-postgresql-first.md
```

**Modified (10)**

```text
api/config.py                        API_ENV + rate-limit budgets
api/main.py                          assert_auth_configured() + middleware registration
api/auth.py                          corrected docstring
api/routers/csv_routes.py            upload audit; delete refactored onto shared writer
evals/runner.py                      Tier E and Tier X runners; import re; psql --set binding
tests/conftest.py                    rate limits disabled for the suite; limiter reset fixture
scripts/lint.sh                      new modules added to the lint gate
Makefile                             eval targets now p,i,s,e,x
.github/workflows/quality-gate.yml   Tier X in free tier; Tiers E and X in integration
.github/workflows/python-validator-tests.yml   Tier X on Windows
docs/GAP_ANALYSIS.md                 G3 closed; engine parity deferred per ADR-0001
docs/VCRM_GAPS.md                    BR-01/BR-15 resolved, BR-02 deferred, frontend note, decision log
docs/VCRM.md                         BR-02 annotated deferred; stale 77% coverage corrected to 86%
```

---

## Suggested next steps

1. ~~Decide BR-02's target scope per engine~~ — **done.** Deferred by [ADR-0001](adr/0001-postgresql-first.md): PostgreSQL first.
2. **Run the integration CI job** to give Tier E its first real four-environment execution. This is now the main outstanding verification.
3. **Set `API_ENV` and `API_KEY` in the Azure deployment** before the next deploy — the API now refuses to start without a key when `API_ENV` is not `dev`, which is the intended behaviour but will surface as a startup failure if the variables are not set.
4. **Consider pruning** `.claude/worktrees/velvety-chasing-badger/` if it is dead.
5. ~~Tier X scenario 02 for MariaDB~~ — deferred with the rest of multi-engine work. It stays the cheapest next engine when ADR-0001 is revisited.
