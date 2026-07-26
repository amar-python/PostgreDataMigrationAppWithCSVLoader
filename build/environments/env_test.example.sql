-- env_test.example.sql  (TEMPLATE - safe to commit; no real secrets)
-- Copy to env_test.sql (gitignored) and fill in, or inject app_password at deploy.
\set env_label          TEST
\set db_name            te_mgmt_test
\set db_owner           postgres
\set schema_name        te_test
\set app_user           te_test_user
\set app_password       '__INJECT_AT_DEPLOY__'
\set conn_limit         15
\set include_seed_data  true
-- Table names (required by te_core_schema.sql - do not omit)
\set tbl_organisations      organisations
\set tbl_personnel          personnel
\set tbl_test_programs      test_programs
\set tbl_temp_documents     temp_documents
\set tbl_test_phases        test_phases
\set tbl_requirements       requirements
\set tbl_test_cases         test_cases
\set tbl_vcrm_entries       vcrm_entries
\set tbl_test_events        test_events
\set tbl_test_results       test_results
\set tbl_defect_reports     defect_reports
\set tbl_evidence_artifacts evidence_artifacts

\ir ../te_core_schema.sql
