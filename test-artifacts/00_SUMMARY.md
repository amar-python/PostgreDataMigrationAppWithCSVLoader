# Test Artifacts — Verification Run

**Run:** `20260721T080414Z`  
**Commit:** `b255262ad97b` (base `b255262` + audit changes)  
**PostgreSQL:** 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)  
**Python:** Python 3.12.3  
**Platform:** Ubuntu 24.04 container, clean clone

## Results

| # | Artifact | What it proves | Result |
|---|---|---|---|
| 01 | `01_provision.log` | All 4 environments provisioned from committed templates | PASS |
| 02 | `02_deploy_dev.log` | Fresh-clone deploy succeeds: 12 tables, seed loaded | PASS |
| 03 | `03_sql_test_suite.log` | Full SQL suite | **142 / 142 — 100%** |
| 04 | `04_evals_p_i_s.log` | Eval tiers P, I, S | **25 / 25, 0 skipped** |
| 05 | `05_test_report_full.log` | Full suite with skip accounting | **54 / 54, 0 skipped, 0 not run** |
| 06 | `06_lint.log` | flake8 + bandit | PASS |
| 07 | `07_health_check.log` | Repository health check | PASS |
| 08 | `08_test_report_dbfree_markers.log` | Windows-job scope; 15 not-run listed by name | PASS |
| 09 | `09_negative_control_unprovisioned.log` | Missing prerequisites FAIL, never skip | **RESULT: FAIL (intended)** |
| 10 | `10_evals_summary.json` | Machine-readable eval outcomes | 25 / 25 |
| 11 | `11_vcrm_gap_report.md` | Per-run VCRM traceability | generated |

## Reading these

Artifacts **01–08** are the green path: every gate passes, nothing is skipped.

Artifact **09 is a deliberate failure** and is the most important one. It runs
the suite with no environment files, no `config.local.env` and no deployed
databases. It reports `RESULT: FAIL` with **0 skipped** — proving that an
unavailable prerequisite fails loudly instead of quietly skipping. Before this
change, that same state reported green.

Artifact **08** shows `NOT RUN : 15`, each named. Those are deselected by the
marker filter (they run in the Linux integration job), not skipped.

## Reproduce

```bash
bash scripts/provision_full_test_env.sh
python3 scripts/test_report.py --strict
```
