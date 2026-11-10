.PHONY: test-free test-gate test-evals test-e2e test-all \
        test-unit test-system test-egress-blocked check-bundle test-sit test-performance test-accessibility test-uat \
        lint lint-diff health \
        eval-list eval-compare eval-summary select-tests \
        csv-load csv-list csv-demo

# ── Test tiers ────────────────────────────────────────────────────────────────

# Free: unit + regression + security + snapshot — no database, no network.
# Mirrors: bun test (free tier in gstack)
test-free:
	pytest -m "unit or regression or security or snapshot" tests/ -v

# Gate: everything in test-free + coverage report. CI default, blocks merge.
# Mirrors: bun run test:gate
test-gate:
	pytest -m "unit or regression or security or snapshot" tests/ \
	    --cov=build/csv --cov=evals --cov-report=term-missing

# Evals: Tier P (offline) + Tier I/S (skip cleanly if no PostgreSQL).
# Mirrors: bun run test:evals
test-evals:
	python3 evals/runner.py --tiers p,i,s,e --verbose

# E2E: full pipeline tests that require a running PostgreSQL instance.
# Mirrors: bun run test:e2e
test-e2e:
	pytest -m "e2e or integration or parity" tests/ -v

# All: every test tier including evals. Accessibility scans need a browser and the
# frontend, so they run on their own: `make test-accessibility` (tests/accessibility/README.md).
# Mirrors: bun run test:evals:all
test-all:
	pytest tests/ -m "not accessibility" --cov=build/csv --cov=evals --cov-report=term-missing
	python3 evals/runner.py --tiers p,i,s,e --verbose

# ── One category at a time (#167) ─────────────────────────────────────────────
# tests/ is split by what a test needs: unit (nothing), system (the API and
# PostgreSQL), system_integration (whole pipeline, all environments), then
# performance, accessibility and uat. See tests/README.md.

# pytest exits 5 when a folder holds no tests yet; that is not a failure for a
# category that has none so far.
define run_category
	python3 -m pytest $(1) -v; rc=$$?; if [ $$rc -eq 5 ]; then echo "No tests in $(1) yet."; exit 0; fi; exit $$rc
endef

test-unit:
	$(call run_category,tests/unit)

test-system:
	$(call run_category,tests/system)

# Egress blocked (M7, #111; BR-37): the API tests with any connection that isn't to this machine refused and
# recorded. Fails if the application tries one, even if the code swallows the error. See docs/SOVEREIGNTY.md.
test-egress-blocked:
	python3 -m pytest tests/system --block-egress -v

# Scan a built frontend for anything it could load from outside (M7). Build first: cd csv-table-hub-main && npm ci && npx vite build
check-bundle:
	python3 scripts/check_bundle_egress.py csv-table-hub-main/.output

test-sit:
	$(call run_category,tests/system_integration)

test-performance:
	$(call run_category,tests/performance)

test-accessibility:
	$(call run_category,tests/accessibility)

test-uat:
	$(call run_category,tests/uat)

# ── Code quality ──────────────────────────────────────────────────────────────

# Full flake8 + bandit scan over all Python source.
# Mirrors: bun run slop
lint:
	bash scripts/lint.sh

# Lint only Python files changed on this branch vs origin/main.
# Mirrors: bun run slop:diff
lint-diff:
	bash scripts/lint_diff.sh

# ── Health & eval tooling ─────────────────────────────────────────────────────

# Component health dashboard — walks every expected file and reports PASS/FAIL.
# Mirrors: bun run skill:check
health:
	python3 scripts/health_check.py

# List all past eval runs.
# Mirrors: bun run eval:list
eval-list:
	python3 scripts/eval_list.py

# Compare two eval runs side-by-side (auto-picks the two most recent).
# Mirrors: bun run eval:compare
eval-compare:
	python3 scripts/eval_compare.py

# Aggregate pass/fail/skip stats across all stored eval runs.
# Mirrors: bun run eval:summary
eval-summary:
	python3 scripts/eval_summary.py

# Show which pytest tests would run given the current git diff.
# Mirrors: bun run eval:select
select-tests:
	python3 scripts/select_tests.py

# ── CSV loader / utiliser ─────────────────────────────────────────────────────

# Load any CSV file into the target environment's database.
# Usage: make csv-load FILE=path/to.csv [ENV=dev] [ENGINE=postgresql]
csv-load:
	@if [ -z "$(FILE)" ]; then \
	    echo "Usage: make csv-load FILE=path/to.csv [ENV=dev] [ENGINE=postgresql]"; \
	    exit 1; \
	fi
	bash build/csv_loader.sh "$(FILE)" --env $(or $(ENV),dev) $(if $(ENGINE),--engine $(ENGINE),)

# List CSV-loaded tables in the target environment.
# Usage: make csv-list [ENV=dev]
csv-list:
	bash build/csv_utilise.sh list --env $(or $(ENV),dev)

# One-shot proof: load the three sample CSVs into dev, then list them.
# Usage: make csv-demo [ENV=dev]
csv-demo:
	bash build/csv_loader.sh build/csv/samples/customers.csv --env $(or $(ENV),dev)
	bash build/csv_loader.sh build/csv/samples/orders.csv    --env $(or $(ENV),dev)
	bash build/csv_loader.sh build/csv/samples/inventory.csv --env $(or $(ENV),dev)
	bash build/csv_utilise.sh list --env $(or $(ENV),dev)

# ── Cross-engine evals (opt-in) ───────────────────────────────────────────────
# Multi-engine support is deferred by docs/adr/0001-postgresql-first.md, so Tier X
# is not part of the default tiers or of CI. It needs no database service, so it
# can be run on demand at any time.
.PHONY: evals-engines
evals-engines:
	python3 evals/runner.py --tiers x --verbose
