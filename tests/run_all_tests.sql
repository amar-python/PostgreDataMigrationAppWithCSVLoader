-- =============================================================================
-- DEFENCE T&E — MASTER TEST RUNNER  (tests/run_all_tests.sql)
-- =============================================================================
-- Usage (run from the te_database_setup/ directory):
--
--   psql -U postgres -d te_mgmt_dev  -f tests/run_all_tests.sql \
--        --set schema_name=te_dev    \
--        --set tbl_organisations=organisations \
--        --set tbl_personnel=personnel \
--        --set tbl_test_programs=test_programs \
--        --set tbl_temp_documents=temp_documents \
--        --set tbl_test_phases=test_phases \
--        --set tbl_requirements=requirements \
--        --set tbl_test_cases=test_cases \
--        --set tbl_vcrm_entries=vcrm_entries \
--        --set tbl_test_events=test_events \
--        --set tbl_test_results=test_results \
--        --set tbl_defect_reports=defect_reports \
--        --set tbl_evidence_artifacts=evidence_artifacts
--
-- Or use the wrapper script which sets everything automatically:
--   ./tests/run_tests.sh dev
--   ./tests/run_tests.sh test
-- =============================================================================

\echo ''
\echo '============================================================'
\echo ' DEFENCE T&E TEST SUITE'
\echo ' Schema:' :schema_name
\echo '============================================================'
\echo ''

-- ── Step 1: Load the test framework (results table + assertion functions) ─────

-- Set search_path so framework objects and assertions resolve without schema prefix.
-- Expose per-env vars via current_setting() for PL/pgSQL DO blocks (:'var' doesn't
-- substitute inside $dollar-quoted$ strings in psql 18).
SELECT
   set_config('search_path',    :'schema_name' || ',public', false),
   set_config('te.schema_name', :'schema_name',              false),
   set_config('te.app_user',    :'app_user',                 false),
   set_config('te.conn_limit',  :'conn_limit',               false);

\echo '>> Loading test framework...'
\i tests/framework/test_framework.sql

\echo ''
\echo '>> Running test suites...'
\echo ''

-- ── Step 2: Run suites in dependency order ────────────────────────────────────
\i tests/suites/test_01_organisations_personnel.sql
\i tests/suites/test_02_programs_phases.sql
\i tests/suites/test_03_requirements_vcrm.sql
\i tests/suites/test_04_execution_defects.sql
\i tests/suites/test_05_schema_and_business_rules.sql

-- ── Step 3: Reports ───────────────────────────────────────────────────────────

\echo ''
\echo '============================================================'
\echo ' REPORT 1: Suite Summary'
\echo '============================================================'

SELECT
   suite,
   total,
   passed,
   failed,
   skipped,
   pass_rate,
   suite_status
FROM :"schema_name".report_suite_summary();

\echo ''
\echo '============================================================'
\echo ' REPORT 2: Failures Only (empty = all green)'
\echo '============================================================'

SELECT
   suite,
   test_name,
   expected,
   actual,
   message
FROM :"schema_name".report_failures();

\echo ''
\echo '============================================================'
\echo ' REPORT 3: Full Detail (all assertions)'
\echo '============================================================'

SELECT
   suite,
   test_name,
   status,
   expected,
   actual,
   message
FROM :"schema_name".report_detail();

\echo ''
\echo '============================================================'
\echo ' REPORT 4: Overall Result'
\echo '============================================================'

SELECT
   total_tests,
   passed,
   failed,
   skipped,
   pass_rate,
   overall
FROM :"schema_name".report_totals();

\echo ''
\echo '============================================================'
\echo ' Test run complete.'
\echo '============================================================'
\echo ''
