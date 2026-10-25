# Engine parity — deferred work, measured state

> **Status: deferred by decision, 2026-09-10.**
> Multi-engine support is deferred until the PostgreSQL milestone is reached —
> see [ADR-0001](adr/0001-postgresql-first.md) for the decision, its rationale,
> and its revisit triggers. This file is the measured state and the open
> questions, kept so the work can be picked up without re-deriving any of it.
>
> **This is not a to-do list for now.** Nothing here is scheduled.

Raised while building the Tier X eval (O-08). The measurements below are what
made the decision possible: before Tier X, the six-engine claim rested on code
review and nobody had counted.

**Nothing in this file is asserted by a test today.** Tier X scenario 01 pins
SQLite's *current* 7-table baseline and fails on drift; it deliberately does not
assert full parity. It is also **no longer run in CI** (ADR-0001) — run it on
demand with `make evals-engines`. See
`evals/datasets/tier_x/01_sqlite_schema_structure/NOTES.txt`.

---

## Measured state

Counted from `CREATE TABLE` statements in each engine's `te_core_schema.sql`
on 2026-09-10.

| Engine | Tables defined | Against PostgreSQL's 12 | Artifacts present |
|---|---|---|---|
| **postgresql** | 12 | reference | `te_core_schema.sql`, `te_seed_data.sql` |
| **sqlite** | 7 | 5 missing | `te_core_schema.sql`, `te_seed_data.sql` |
| **mariadb** | 7 | 5 missing | `te_core_schema.sql`, `te_seed_data.sql` |
| **teradata** | 1 | 11 missing | `te_core_schema.sql` (skeletal) |
| **influxdb** | n/a | no DDL at all | `te_seed_data.lp` only |
| **redis** | n/a | no DDL at all | `te_seed_data.sh` only |

## Missing from both SQLite and MariaDB

The same five, in both engines:

- `temp_documents`
- `test_phases`
- `test_events`
- `test_results`
- `evidence_artifacts`

These are the execution and evidence half of the model. What is present in
SQLite and MariaDB is the planning half — organisations, personnel, programs,
requirements, test cases, VCRM entries, defects. So both engines can hold a test
*plan* and its traceability, but not a record of test *execution*.

That matters for the BR-02 claim specifically: an engine that cannot store
`test_results` or `evidence_artifacts` cannot support the T&E workflow the
framework exists to serve, even though its adapter script runs and its DDL
deploys cleanly.

## Why this went unnoticed

`build/adapters/adapter_<engine>.sh` deploys whatever DDL it is given and reports
success on exit 0. With no cross-engine eval, "the adapter ran" was the only
signal available, and it was a true statement about an incomplete schema. This is
the failure mode Tier X exists to close.

## Open questions for when this resumes

These are the questions to answer first; ADR-0001 defers them rather than
answering them.

1. **Target scope per engine.** Is SQLite meant to reach full 12-table parity, or
   is it deliberately a planning-only subset for local/offline use? Same question
   for MariaDB. The answer changes whether the 5 tables are a gap or a design
   choice — and if it is a design choice, it belongs in `docs/ARCHITECTURE.md`
   rather than in a TODO.
2. **Teradata.** 1 of 12 is closer to a placeholder than an implementation.
   Either schedule the DDL or drop the claim to "planned".
3. **InfluxDB and Redis.** Neither is relational, so "12 tables" does not
   translate. What would count as supported — seed data landing in the expected
   measurements / key namespaces? That needs defining before it can be verified.
4. **BR-02 wording in `docs/VCRM.md`.** ✅ **Settled 2026-09-10.** The wording is
   retained unchanged and annotated as deferred by decision, pointing at
   ADR-0001. It states the eventual target, not the current milestone. BR-02's
   VCRM status moved from ❌ Not verified to ⏸ Deferred by decision.

## If you take on the SQLite tables

Order them by dependency, since each references the one before:

```
test_phases      -> references test_programs
test_events      -> references test_phases
test_results     -> references test_events, test_cases
evidence_artifacts -> references test_results
temp_documents   -> references test_programs   (independent of the chain above)
```

Then, in the same commit, move each table from `known_missing_tables` into
`expected_tables` in
`evals/expected/tier_x/01_sqlite_schema_structure.json`. Tier X will fail until
you do — `tests/test_evals_tier_e_x.py` asserts that the two lists together
account for all 12 tables, and that everything listed as missing is genuinely
absent. That is the reminder working as designed.

## Cheapest next engine after SQLite

MariaDB. It needs a service, but `docker run mariadb` is a ~10-minute setup and
the DDL is already 7 tables in, so a Tier X scenario 02 would follow the same
shape as 01 with a real connection instead of an in-memory one.
