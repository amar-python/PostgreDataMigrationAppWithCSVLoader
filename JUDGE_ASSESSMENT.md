# LLM-as-a-Judge — Assessment Record

Tier J grades the project's **non-deterministic artifacts** (narratives,
documentation, AI-authored changes) against the **deterministic evidence** the
existing tiers already produce. It never replaces Tier P/I/S: if a check can be
deterministic, it stays deterministic.

Scoring uses a discrete **1–4 scale** with anchored definitions, reasoning
before the score (MEC), and mandatory evidence quotes. A score of 0 means
*insufficient evidence to grade* and is a valid outcome, not a failure.

---

## Assignment types

| ID | Artifact graded | Deterministic ground truth |
|---|---|---|
| J1 | Per-run gap report (`VCRM_GAPS_<run_id>.md`) | `summary.json` from the same run |
| J2 | Documentation claims (README, QUICKSTART, …) | Observed repository and runtime state |
| J3 | AI-authored code changes | Tier P/I/S outcomes before vs after |
| J4 | External review triage (e.g. Copilot) | What the repository actually contains |

J1 and J2 are assessed below. J3 and J4 are defined but not yet run.

---

## J1 — Gap-report fidelity

### Rubric anchors

| Score | Definition |
|---|---|
| 4 | Every status matches the run evidence exactly; nothing material omitted |
| 3 | Statuses correct; minor wording drift or one immaterial omission |
| 2 | At least one status overstated or understated |
| 1 | Narrative contradicts the evidence |

### Assessment 1 — failure regime (pilot)

The first PostgreSQL-backed run in the project's history: Tier P passed 23/23
while Tiers I and S both failed. The generator had never operated under failure
before.

Reasoning: it marked **14 BRs REGRESSION**, 2 VERIFIED, 4 UNVERIFIED, with
per-BR evidence strings naming the failing scenario, e.g.
`BR-20 | REGRESSION | … | tier_s/01_fresh_deploy_then_all_tests_pass: FAIL`.
No status overstated the evidence.

Verdict — **4 / 4**

### Assessment 2 — success regime (current)

Re-run after the deploy defects were fixed.

| Evidence | Value |
|---|---|
| `summary.json` totals | `{total: 25, passed: 25, failed: 0, skipped: 0}` |
| Gap-report statuses | 17 OK, 2 GAP, 2 DEFERRED, 1 PARTIAL (22 BRs) |
| REGRESSION rows | **0** |

Reasoning: with every eval passing, any REGRESSION would be a false positive —
there are none. The 22 BRs account exactly. The remaining GAP/DEFERRED/PARTIAL
entries correspond to Tiers X and E, which are unimplemented by design, so
declining to claim verification for them is correct rather than pessimistic.

Verdict — **4 / 4**. No fix required.

The generator has now been graded under both failure and success regimes and
was faithful in each.

---

## J2 — Documentation claims

### Rubric anchors

| Score | Definition |
|---|---|
| 4 | Every quantitative claim matches observed reality |
| 3 | All claims correct; minor wording imprecision |
| 2 | Multiple material misstatements a reader would act on |
| 1 | Claims contradict reality throughout |

### Assessment 1 — pilot

Three material misstatements:

| Claim | Documented | Actual |
|---|---|---|
| SQL assertions | 85 | 109 (at that commit) |
| Eval outcome with PostgreSQL | `25/25, failed: 0` | 23 passed, 2 failed |
| Deploy result | database `te_dev`, 6 core tables | `te_mgmt_dev`, 12 tables |

Each would mislead someone validating their first deploy.

Verdict — **2 / 4**

### Assessment 2 — after remediation

| Claim | Documented | Verified actual | Status |
|---|---|---|---|
| SQL assertions | 142 | `142 \| 142 \| 0 \| 0 \| 100.0%` | ✅ |
| Eval outcome | 25 / 25 | `total: 25, passed: 25, failed: 0` | ✅ |
| Deploy result | `te_mgmt_dev`, 12 core tables | `te_mgmt_dev`, 12 (13 after tests) | ✅ **fixed** |
| Tier P scenarios | 23 | 23 expectation files | ✅ |
| SQL suites | 5 | 5 suite files | ✅ |

Verdict — **4 / 4**

### Fix applied

The assertion count and eval-outcome claims were corrected during the
documentation audit. The deploy description was the last outstanding defect and
was corrected here — `QUICKSTART.md` had claimed the deploy produces a database
named `te_dev` with **6** core tables. It produces `te_mgmt_dev` with **12**;
the schema (not the database) is `te_dev`. The note about
`test_run_results` appearing as a 13th table after the SQL suite runs was added
so the two counts cannot be mistaken for a discrepancy.

---

## Method note

Every figure above was produced by execution, not by reading code. This matters:
a static grep of `assert_*` call sites returns **131**, but the suite reports
**142**, because some assertions run inside loops. The lower number would have
looked plausible and been wrong — which is precisely the failure mode an
evidence-anchored judge exists to catch.

---

## Not yet assessed

| ID | Blocker |
|---|---|
| J3 | Needs before/after Tier P/I/S outcomes captured around a specific AI-authored change |
| J4 | Golden set exists (the manual Copilot triages) but has not been formalised |

Before any judge score gates anything automatically, the calibration gate in the
plan applies: agreement with human labels at Cohen's kappa ≥ 0.7 per assignment
type.
