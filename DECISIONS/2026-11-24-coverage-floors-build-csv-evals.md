# Coverage floors for build/csv and evals: measure child processes, then gate

- **Date:** 2026-11-24
- **Issue:** #304 (OIT-019, BR-48)
- **Status:** Decided

## Context

`build/csv` and `evals` were in the coverage scope but had no floor. They read low (0 % and 39 % on the full suite,
19 Nov) because the tests run `build/csv/validator.py` and `evals/runner.py` as child processes, which coverage.py did
not follow. A floor on a number that does not measure the code would mean nothing, so the fix plan offered two options:
(a) measure the child processes and add floors, or (b) record an exemption.

## Decision

Option (a). `.coveragerc` sets `patch = subprocess` (coverage.py 7.10 and later; the locks install 7.17), so every
Python child process a measured test starts is measured too, and pytest-cov combines the data. Then
`scripts/check_coverage_floors.py` gates both packages:

| Package | Measured 24 Nov 2026 (database-free tiers, Python 3.12) | Floor |
|---|---|---|
| `build/csv/` | 85.9 % (validator.py: 0 % before this change) | 80 % |
| `evals/` | 63.5 % | 60 % |

These figures come from the database-free markers only, so they are a lower bound: the CI coverage job measures the
whole suite, which also runs the database tiers. The floors are applied by the existing `coverage` job in
`quality-gate.yml`.

## Not covered

The shell loaders in `build/csv/` (`loader_*.sh`, `validator.sh`) are invisible to coverage.py and are not in the
figure. They are verified by the tests that run them, not by a percentage.

## Revisit when

The full-suite figures in the CI coverage report sit well above the floors: raise the floors to a few points under
them, as for `api/` and `streamlit_app/`.
