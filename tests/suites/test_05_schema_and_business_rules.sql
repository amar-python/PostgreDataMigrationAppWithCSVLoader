-- =============================================================================
-- TEST SUITE: SCHEMA STRUCTURE, INDEXES, TRIGGERS & BUSINESS RULES
-- File: tests/suites/test_05_schema_and_business_rules.sql
-- =============================================================================
-- psql 18 does not substitute :'var' or :"var" inside $dollar-quoted$ DO blocks.
-- All per-env values are read via current_setting('te.*') which run_all_tests.sql
-- populates with set_config() before this file is loaded. Table names are fixed
-- across all environments so they are used unqualified (search_path handles schema).
-- =============================================================================

\echo '   [suite 05] schema structure, indexes, triggers & business rules'

DO
$$
DECLARE
   v_count     BIGINT;
   v_ts1       TIMESTAMPTZ;
   v_ts2       TIMESTAMPTZ;
   v_schema    TEXT   := current_setting('te.schema_name');
   v_app_user  TEXT   := current_setting('te.app_user');
   v_conn_lim  BIGINT := current_setting('te.conn_limit')::BIGINT;
BEGIN

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION P: SCHEMA STRUCTURE — Table existence
-- ─────────────────────────────────────────────────────────────────────────────

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'organisations';
   PERFORM assert_equals('schema', 'P01 — Table organisations exists',    1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'personnel';
   PERFORM assert_equals('schema', 'P02 — Table personnel exists',        1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'test_programs';
   PERFORM assert_equals('schema', 'P03 — Table test_programs exists',    1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'temp_documents';
   PERFORM assert_equals('schema', 'P04 — Table temp_documents exists',   1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'test_phases';
   PERFORM assert_equals('schema', 'P05 — Table test_phases exists',      1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'requirements';
   PERFORM assert_equals('schema', 'P06 — Table requirements exists',     1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'test_cases';
   PERFORM assert_equals('schema', 'P07 — Table test_cases exists',       1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'vcrm_entries';
   PERFORM assert_equals('schema', 'P08 — Table vcrm_entries exists',     1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'test_events';
   PERFORM assert_equals('schema', 'P09 — Table test_events exists',      1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'test_results';
   PERFORM assert_equals('schema', 'P10 — Table test_results exists',     1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'defect_reports';
   PERFORM assert_equals('schema', 'P11 — Table defect_reports exists',   1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM information_schema.tables
   WHERE table_schema = v_schema AND table_name = 'evidence_artifacts';
   PERFORM assert_equals('schema', 'P12 — Table evidence_artifacts exists', 1::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION Q: INDEXES — Critical indexes exist
-- ─────────────────────────────────────────────────────────────────────────────

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_personnel_org';
   PERFORM assert_equals('schema', 'Q01 — Index idx_personnel_org exists',          1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_programs_status';
   PERFORM assert_equals('schema', 'Q02 — Index idx_programs_status exists',        1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_testcases_phase';
   PERFORM assert_equals('schema', 'Q03 — Index idx_testcases_phase exists',        1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_results_verdict';
   PERFORM assert_equals('schema', 'Q04 — Index idx_results_verdict exists',        1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_defects_severity';
   PERFORM assert_equals('schema', 'Q05 — Index idx_defects_severity exists',       1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_vcrm_req';
   PERFORM assert_equals('schema', 'Q06 — Index idx_vcrm_req exists',               1::BIGINT, v_count);

   SELECT COUNT(*) INTO v_count FROM pg_indexes
   WHERE schemaname = v_schema AND indexname = 'idx_personnel_email_trgm';
   PERFORM assert_equals('schema', 'Q07 — GIN trigram index idx_personnel_email_trgm exists', 1::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION R: TRIGGERS — updated_at fires on UPDATE
-- ─────────────────────────────────────────────────────────────────────────────

   -- R01: updating organisations updates updated_at
   DECLARE
      v_org_id UUID;
   BEGIN
      SELECT org_id INTO v_org_id FROM organisations LIMIT 1;
      SELECT updated_at INTO v_ts1 FROM organisations WHERE org_id = v_org_id;

      PERFORM pg_sleep(0.01);

      EXECUTE format('UPDATE %I.%I SET is_active = is_active WHERE org_id = %L',
                     v_schema, 'organisations', v_org_id);
      SELECT updated_at INTO v_ts2 FROM organisations WHERE org_id = v_org_id;

      PERFORM assert_true(
         'schema', 'R01 — Trigger fires: organisations.updated_at advances on UPDATE',
         (v_ts2 > v_ts1)::TEXT
      );
   END;

   -- R02: updating test_programs updates updated_at
   DECLARE
      v_prog_id UUID;
   BEGIN
      SELECT program_id INTO v_prog_id FROM test_programs LIMIT 1;
      SELECT updated_at INTO v_ts1 FROM test_programs WHERE program_id = v_prog_id;

      PERFORM pg_sleep(0.01);

      EXECUTE format('UPDATE %I.%I SET status = status WHERE program_id = %L',
                     v_schema, 'test_programs', v_prog_id);
      SELECT updated_at INTO v_ts2 FROM test_programs WHERE program_id = v_prog_id;

      PERFORM assert_true(
         'schema', 'R02 — Trigger fires: test_programs.updated_at advances on UPDATE',
         (v_ts2 > v_ts1)::TEXT
      );
   END;

   -- R03: trigger registered on personnel table
   SELECT COUNT(*) INTO v_count
   FROM information_schema.triggers
   WHERE trigger_schema = v_schema
   AND   event_object_table = 'personnel'
   AND   trigger_name = 'trg_updated_at';
   PERFORM assert_equals('schema', 'R03 — Trigger trg_updated_at registered on personnel',      1::BIGINT, v_count);

   -- R04: trigger registered on defect_reports table
   SELECT COUNT(*) INTO v_count
   FROM information_schema.triggers
   WHERE trigger_schema = v_schema
   AND   event_object_table = 'defect_reports'
   AND   trigger_name = 'trg_updated_at';
   PERFORM assert_equals('schema', 'R04 — Trigger trg_updated_at registered on defect_reports', 1::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION S: BUSINESS RULES — Cross-table logic
-- ─────────────────────────────────────────────────────────────────────────────

   -- S01: every test result's test case belongs to the same program as its event
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events  ev ON ev.event_id = tr.event_id
   JOIN test_phases  ph ON ph.phase_id = ev.phase_id
   JOIN test_cases   tc ON tc.tc_id    = tr.tc_id
   WHERE tc.phase_id != ev.phase_id;
   PERFORM assert_equals('business_rules',
      'S01 — All results: test case phase matches event phase', 0::BIGINT, v_count);

   -- S02: fail verdicts all have a DR raised against the same program
   SELECT COUNT(*) INTO v_count
   FROM test_results  tr
   JOIN test_events   ev ON ev.event_id   = tr.event_id
   JOIN test_phases   ph ON ph.phase_id   = ev.phase_id
   JOIN test_programs tp ON tp.program_id = ph.program_id
   WHERE tr.verdict = 'fail'
   AND NOT EXISTS (
      SELECT 1 FROM defect_reports dr
      WHERE dr.result_id  = tr.result_id
      AND   dr.program_id = tp.program_id
   );
   PERFORM assert_equals('business_rules',
      'S02 — All fail verdicts have a matching DR raised', 0::BIGINT, v_count);

   -- S03: no test results exist for events that are still 'planned'
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events  ev ON ev.event_id = tr.event_id
   WHERE ev.status = 'planned';
   PERFORM assert_equals('business_rules',
      'S03 — No results recorded against planned (future) events', 0::BIGINT, v_count);

   -- S04: all open defects belong to an active program
   SELECT COUNT(*) INTO v_count
   FROM defect_reports dr
   JOIN test_programs  tp ON tp.program_id = dr.program_id
   WHERE dr.status = 'open'
   AND   tp.status NOT IN ('active');
   PERFORM assert_equals('business_rules',
      'S04 — All open DRs belong to an active program', 0::BIGINT, v_count);

   -- S05: no baseline-cleared personnel authoring cases in PROTECTED+ programs
   SELECT COUNT(*) INTO v_count
   FROM test_cases    tc
   JOIN test_phases   ph ON ph.phase_id   = tc.phase_id
   JOIN test_programs tp ON tp.program_id = ph.program_id
   JOIN personnel     p  ON p.person_id   = tc.author_id
   WHERE tp.classification IN ('PROTECTED','SECRET','TOP SECRET')
   AND   p.clearance = 'baseline';
   PERFORM assert_equals('business_rules',
      'S05 — No baseline-cleared personnel authoring cases in PROTECTED+ programs',
      0::BIGINT, v_count);

   -- S06: all VCRM entries belong to the same program as their requirement
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries  v
   JOIN requirements  r  ON r.req_id    = v.req_id
   JOIN test_cases    tc ON tc.tc_id    = v.tc_id
   JOIN test_phases   ph ON ph.phase_id = tc.phase_id
   WHERE r.program_id != ph.program_id;
   PERFORM assert_equals('business_rules',
      'S06 — All VCRM entries: requirement and test case share same program',
      0::BIGINT, v_count);

   -- S07: no event has planned_end before planned_start
   SELECT COUNT(*) INTO v_count
   FROM test_events
   WHERE planned_end IS NOT NULL AND planned_end < planned_start;
   PERFORM assert_equals('business_rules',
      'S07 — No test events have planned_end before planned_start', 0::BIGINT, v_count);

   -- S08: evidence_artifacts table exists and is empty (no results linked yet)
   SELECT COUNT(*) INTO v_count FROM evidence_artifacts;
   PERFORM assert_equals('business_rules',
      'S08 — evidence_artifacts table is empty (no files uploaded yet)', 0::BIGINT, v_count);

   -- ─────────────────────────────────────────────────────────────────────────
   -- S09–S10: Per-environment PG role connection limit (closes BR-15 gap).
   -- Each env_*.sql sets \set app_user and \set conn_limit; run_all_tests.sql
   -- forwards these via set_config('te.app_user') / set_config('te.conn_limit').
   -- A typo in any env file (e.g. conn_limit=5 instead of 50 in env_prod.sql)
   -- is now caught here before reaching production.
   -- ─────────────────────────────────────────────────────────────────────────

   -- S09: app role exists in pg_roles
   SELECT COUNT(*) INTO v_count FROM pg_roles WHERE rolname = v_app_user;
   PERFORM assert_equals('business_rules', 'S09 — App role exists in pg_roles',
      1::BIGINT, v_count);

   -- S10: app role rolconnlimit matches the env's conn_limit
   SELECT COALESCE(rolconnlimit, -999) INTO v_count FROM pg_roles WHERE rolname = v_app_user;
   PERFORM assert_equals('business_rules', 'S10 — App role conn limit matches env config',
      v_conn_lim, v_count);

END;
$$;
