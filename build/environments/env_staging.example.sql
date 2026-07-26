-- env_staging.example.sql  (TEMPLATE - safe to commit; no real secrets)
-- Copy to env_staging.sql (gitignored) and fill in, or inject app_password at deploy.
\set env_label          STAGING
\set db_name            te_mgmt_staging
\set db_owner           postgres
\set schema_name        te_staging
\set app_user           te_stg_user
\set app_password       '__INJECT_AT_DEPLOY__'
\set conn_limit         25
\set include_seed_data  false
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
