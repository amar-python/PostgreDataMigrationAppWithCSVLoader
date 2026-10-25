# ADR-0001 — PostgreSQL first; multi-engine support deferred

- **Status:** Accepted
- **Date:** 2026-09-10
- **Decision maker:** Amarnath Rasineni
- **Affects:** BR-02 in `docs/VCRM.md`, Tier X in `evals/`, `build/adapters/*`, `build/schema/*`

---

## Context

The repository ships adapter scripts and schema directories for six database
engines — PostgreSQL, MariaDB, SQLite, InfluxDB, Redis, Teradata — and BR-02
states the framework supports all six. Until now that claim rested on code
review: only PostgreSQL was ever executed by a test.

Building the Tier X eval (`01_sqlite_schema_structure`) made the actual state
measurable for the first time. Counting `CREATE TABLE` statements per engine:

| Engine | Tables defined | Against PostgreSQL's 12 |
|---|---|---|
| postgresql | 12 | reference |
| sqlite | 7 | 5 missing |
| mariadb | 7 | 5 missing |
| teradata | 1 | 11 missing |
| influxdb | no DDL (seed `.lp` only) | n/a |
| redis | no DDL (seed `.sh` only) | n/a |

The five tables absent from SQLite and MariaDB are `temp_documents`,
`test_phases`, `test_events`, `test_results` and `evidence_artifacts`. Those are
the execution and evidence half of the T&E model. What is present is the planning
half: organisations, personnel, programs, requirements, test cases, VCRM entries,
defects. So both engines can hold a test plan and its traceability but not a
record of test execution — for a T&E framework, the material half is the one
missing.

This went unnoticed because `adapter_<engine>.sh` deploys whatever DDL it is
handed and reports success on exit 0. With no cross-engine eval, "the adapter
ran" was the only signal available, and it was a true statement about an
incomplete schema.

## Decision

**Pursue PostgreSQL to a working milestone first. Defer multi-engine support
until that milestone is reached.**

BR-02's wording in `docs/VCRM.md` is retained unchanged and annotated as deferred.
It states the eventual target, not the current milestone.

## Rationale

The reasoning is depth before breadth: reach a genuine milestone on one engine,
then apply what that teaches to the others.

Three things support it.

**The lessons transfer; the guesses don't.** Writing five more DDL variants now
would mean guessing at decisions PostgreSQL has not yet settled — how the
execution tables actually get used, which constraints earn their place, where the
indexes belong. Every one of those guesses would need revisiting, in five places,
once PostgreSQL answered the question. Deferring means porting decisions already
proven rather than propagating provisional ones.

**Two of the six engines don't translate structurally anyway.** InfluxDB is
time-series and Redis is key-value; "12 tables" is not a meaningful target for
either. Defining what "supported" means for them is design work in its own right,
and it is cheaper once the relational model is stable.

**Breadth was costing credibility, not buying capability.** Six adapters that
deploy incomplete schemas is weaker than one adapter that is fully verified. The
142-assertion suite, the eval tiers, and the audit trail all exist for
PostgreSQL. Spreading effort across five unverified engines would have diluted
that without making any of them usable.

The counter-argument, recorded honestly: anyone reading BR-02 or the README today
could reasonably start a MariaDB deployment and hit an incomplete schema. That
risk is real. It is mitigated by documentation — this ADR, the BR-02 annotation,
and `docs/ENGINE_PARITY_TODO.md` — rather than by code, which is a weaker
mitigation than removing the adapters would be. Removing them was rejected
because they are a useful starting point for the later work and deleting them
would discard effort already spent.

## Alternatives considered

**Write the missing DDL for SQLite and MariaDB now** (~2 days). Rejected: it
propagates unsettled modelling decisions into two more places, as above.

**Delete the five non-PostgreSQL adapters and schema directories.** Rejected:
strongest possible protection against someone starting an unsupported
deployment, but discards work that will be the basis for the later effort, and
makes the eventual resumption more expensive than it needs to be.

**Restate BR-02 as PostgreSQL-only, dropping the six-engine target.** Rejected:
the multi-engine ambition is real and should stay tracked. A requirement annotated
as deferred keeps it visible; a deleted one quietly stops being anyone's problem.

## Consequences

**Immediate**

- BR-02 moves from ❌ Not verified to ⏸ Deferred by decision. VCRM coverage is
  now 19 of 22 (86 %) verified, with **no unverified requirement that is not a
  recorded decision** — the remaining three are BR-02, BR-21 and BR-22, all
  deferred deliberately.
- Tier X scenario `01_sqlite_schema_structure` and its unit tests **stay in the
  repository** but are **removed from the CI workflows**, so the pipeline is
  purely PostgreSQL. The scenario still passes when run manually
  (`make evals-engines`, or `python3 evals/runner.py --tiers x`).
- Tier E is unaffected and stays in CI: cross-environment parity is PostgreSQL
  work and part of the current milestone.

**When multi-engine work resumes**

- Re-add `x` to the eval tiers in `.github/workflows/quality-gate.yml` and
  `.github/workflows/python-validator-tests.yml`. Tier X needs no database
  service, so it can run in the free tier and on the Windows runner.
- Work through the per-engine questions in `docs/ENGINE_PARITY_TODO.md`,
  starting with target scope per engine.
- As each SQLite table is written, move it from `known_missing_tables` into
  `expected_tables` in
  `evals/expected/tier_x/01_sqlite_schema_structure.json`. Tier X will fail until
  you do — `tests/test_evals_tier_e_x.py` asserts the two lists together account
  for all 12 tables, so the shortfall cannot be understated by omission.
- MariaDB is the cheapest next engine: already 7 tables in, and
  `docker run mariadb` is roughly a ten-minute setup.

**Accepted risk**

Someone could follow the README, pick a non-PostgreSQL engine, and hit an
incomplete schema. Mitigated by documentation only. If this materialises — or if
a non-PostgreSQL engine becomes a delivery commitment — revisit this ADR rather
than patching around it.

## Revisit triggers

Any one of these should reopen the decision:

1. The PostgreSQL milestone is reached — the trigger this decision anticipates.
2. A non-PostgreSQL engine becomes a commitment to a real user or customer.
3. Anyone reports attempting a non-PostgreSQL deployment and hitting the gap.
4. BR-02's wording is challenged in a review as claiming more than the build
   delivers.

## References

- `docs/ENGINE_PARITY_TODO.md` — per-engine measured state and open questions
- `docs/VCRM.md` — BR-02, annotated
- `docs/VCRM_GAPS.md` — BR-02 gap section
- `evals/datasets/tier_x/01_sqlite_schema_structure/NOTES.txt` — what Tier X does and its scope limits
- `evals/PLAN.md`, `evals/FAILURE_MODES.md` — the earlier, implicit "deferred until PG is locked in" note this ADR makes explicit
