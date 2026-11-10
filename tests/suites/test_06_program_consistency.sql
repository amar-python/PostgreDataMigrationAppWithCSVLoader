-- =============================================================================
-- TEST SUITE: PROGRAM CONSISTENCY (BR-05, BR-07, BR-08)  — issue #177
-- File: tests/suites/test_06_program_consistency.sql
-- =============================================================================
-- Two throwaway programs (A and B) are built, then every cross-program join the
-- review found (RV-F2, RV-F9, RV-F8) is attempted and must fail with a
-- foreign_key_violation specifically (a typo in a fixture must not pass as
-- "rejected"). Same-program joins are the positive controls. Fixture rows are
-- removed at the end; the seeded data is never touched.
-- =============================================================================

\echo '   [suite 06] program consistency (composite FKs, coverage grouping)'

DO
$$
DECLARE
   v_org     UUID;
   v_person  UUID;
   v_prog_a  UUID := 'ee000000-0000-0000-0000-00000000000a';
   v_prog_b  UUID := 'ee000000-0000-0000-0000-00000000000b';
   v_ph_a    UUID := 'ee100000-0000-0000-0000-00000000000a';
   v_ph_b    UUID := 'ee100000-0000-0000-0000-00000000000b';
   v_req_a   UUID := 'ee200000-0000-0000-0000-00000000000a';
   v_req_b   UUID := 'ee200000-0000-0000-0000-00000000000b';
   v_tc_a    UUID := 'ee300000-0000-0000-0000-00000000000a';
   v_tc_b    UUID := 'ee300000-0000-0000-0000-00000000000b';
   v_ev_a    UUID := 'ee400000-0000-0000-0000-00000000000a';
   v_ev_b    UUID := 'ee400000-0000-0000-0000-00000000000b';
   v_res_a   UUID := 'ee500000-0000-0000-0000-00000000000a';
   v_count   BIGINT;
   v_prog    UUID;
   v_covered BIGINT;
   v_uncov   BIGINT;
BEGIN
   SELECT org_id    INTO v_org    FROM organisations LIMIT 1;
   SELECT person_id INTO v_person FROM personnel     LIMIT 1;

   -- ── Fixture: programs A and B, each with a phase, requirement, case, event ──
   INSERT INTO test_programs (program_id, org_id, program_code, program_name) VALUES
      (v_prog_a, v_org, 'ZZ-PC-A', 'Program consistency fixture A'),
      (v_prog_b, v_org, 'ZZ-PC-B', 'Program consistency fixture B');
   INSERT INTO test_phases (phase_id, program_id, phase_code, phase_type, phase_name) VALUES
      (v_ph_a, v_prog_a, 'PC-DT', 'DT&E', 'Fixture phase A'),
      (v_ph_b, v_prog_b, 'PC-DT', 'DT&E', 'Fixture phase B');
   -- Same req_identifier in both programs: the RV-F8 trap.
   INSERT INTO requirements (req_id, program_id, req_identifier, title, req_type) VALUES
      (v_req_a, v_prog_a, 'ZZ-REQ-1', 'Same title', 'functional'),
      (v_req_b, v_prog_b, 'ZZ-REQ-1', 'Same title', 'functional');
   -- program_id deliberately omitted: filled from the phase.
   INSERT INTO test_cases (tc_id, phase_id, author_id, tc_identifier, title) VALUES
      (v_tc_a, v_ph_a, v_person, 'ZZ-TC-1', 'Fixture case A'),
      (v_tc_b, v_ph_b, v_person, 'ZZ-TC-2', 'Fixture case B');
   INSERT INTO test_events (event_id, phase_id, event_code, event_name, event_type) VALUES
      (v_ev_a, v_ph_a, 'ZZ-EV-A', 'Fixture event A', 'lab'),
      (v_ev_b, v_ph_b, 'ZZ-EV-B', 'Fixture event B', 'lab');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION S: program_id is derived, not trusted
-- ─────────────────────────────────────────────────────────────────────────────

   SELECT program_id INTO v_prog FROM test_cases WHERE tc_id = v_tc_b;
   PERFORM assert_equals('program_consistency',
      'S01 — test_cases.program_id filled from its phase', v_prog_b, v_prog);

   SELECT program_id INTO v_prog FROM test_events WHERE event_id = v_ev_a;
   PERFORM assert_equals('program_consistency',
      'S02 — test_events.program_id filled from its phase', v_prog_a, v_prog);

   BEGIN
      INSERT INTO test_cases (phase_id, program_id, author_id, tc_identifier, title)
      VALUES (v_ph_a, v_prog_b, v_person, 'ZZ-TC-LIE', 'Phase A, claims program B');
      PERFORM tf_record('program_consistency', 'S03 — test case claiming another program than its phase rejected',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'S03 — test case claiming another program than its phase rejected',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

   BEGIN
      UPDATE test_cases SET phase_id = v_ph_b WHERE tc_id = v_tc_a;
      PERFORM tf_record('program_consistency', 'S04 — moving a test case to another program''s phase rejected',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'S04 — moving a test case to another program''s phase rejected',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION T: VCRM (RV-F2)
-- ─────────────────────────────────────────────────────────────────────────────

   INSERT INTO vcrm_entries (req_id, tc_id) VALUES (v_req_a, v_tc_a);   -- program A, covered
   SELECT COUNT(*) INTO v_count FROM vcrm_entries WHERE req_id = v_req_a AND tc_id = v_tc_a;
   PERFORM assert_equals('program_consistency',
      'T01 — VCRM entry within one program accepted', 1::BIGINT, v_count);

   SELECT program_id INTO v_prog FROM vcrm_entries WHERE req_id = v_req_a AND tc_id = v_tc_a;
   PERFORM assert_equals('program_consistency',
      'T02 — vcrm_entries.program_id filled from its requirement', v_prog_a, v_prog);

   BEGIN
      INSERT INTO vcrm_entries (req_id, tc_id) VALUES (v_req_a, v_tc_b);
      PERFORM tf_record('program_consistency', 'T03 — VCRM joining program A requirement to program B test case rejected',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'T03 — VCRM joining program A requirement to program B test case rejected',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

   BEGIN
      INSERT INTO vcrm_entries (req_id, tc_id, program_id) VALUES (v_req_a, v_tc_b, v_prog_b);
      PERFORM tf_record('program_consistency', 'T04 — VCRM with an explicit program_id cannot bypass the check',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'T04 — VCRM with an explicit program_id cannot bypass the check',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION U: RESULTS (RV-F2)
-- ─────────────────────────────────────────────────────────────────────────────

   INSERT INTO test_results (result_id, event_id, tc_id, executed_by_id, verdict)
   VALUES (v_res_a, v_ev_a, v_tc_a, v_person, 'pass');
   SELECT COUNT(*) INTO v_count FROM test_results WHERE result_id = v_res_a;
   PERFORM assert_equals('program_consistency',
      'U01 — result within one program accepted', 1::BIGINT, v_count);

   BEGIN
      INSERT INTO test_results (event_id, tc_id, executed_by_id, verdict)
      VALUES (v_ev_b, v_tc_a, v_person, 'pass');
      PERFORM tf_record('program_consistency', 'U02 — result joining program A test case to program B event rejected',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'U02 — result joining program A test case to program B event rejected',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION V: DEFECTS (RV-F9)
-- ─────────────────────────────────────────────────────────────────────────────

   INSERT INTO defect_reports (result_id, program_id, raised_by_id, defect_ref, title, severity)
   VALUES (v_res_a, v_prog_a, v_person, 'ZZ-DR-A', 'Same-program defect', 'minor');
   SELECT COUNT(*) INTO v_count FROM defect_reports WHERE defect_ref = 'ZZ-DR-A';
   PERFORM assert_equals('program_consistency',
      'V01 — defect against a result in its own program accepted', 1::BIGINT, v_count);

   BEGIN
      INSERT INTO defect_reports (result_id, program_id, raised_by_id, defect_ref, title, severity)
      VALUES (v_res_a, v_prog_b, v_person, 'ZZ-DR-X', 'Cross-program defect', 'minor');
      PERFORM tf_record('program_consistency', 'V02 — defect in program B against a program A result rejected',
         'FAIL', 'foreign_key_violation', 'no exception');
   EXCEPTION WHEN foreign_key_violation THEN
      PERFORM tf_record('program_consistency', 'V02 — defect in program B against a program A result rejected',
         'PASS', 'foreign_key_violation', 'foreign_key_violation');
   END;

   INSERT INTO defect_reports (result_id, program_id, raised_by_id, defect_ref, title, severity)
   VALUES (NULL, v_prog_b, v_person, 'ZZ-DR-B', 'Defect with no result', 'minor');
   SELECT COUNT(*) INTO v_count FROM defect_reports WHERE defect_ref = 'ZZ-DR-B';
   PERFORM assert_equals('program_consistency',
      'V03 — defect with no result still accepted (result_id is optional)', 1::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION W: COVERAGE GROUPING (RV-F8)
-- Mirrors the "VCRM coverage summary" query in te_core_schema.sql (phase 6).
-- ─────────────────────────────────────────────────────────────────────────────

   SELECT COUNT(*),
          COUNT(*) FILTER (WHERE mapped > 0),
          COUNT(*) FILTER (WHERE mapped = 0)
   INTO   v_count, v_covered, v_uncov
   FROM (
      SELECT r.program_id, r.req_identifier, COUNT(v.tc_id) AS mapped
      FROM       requirements  r
      LEFT JOIN  vcrm_entries  v ON v.req_id = r.req_id AND v.program_id = r.program_id
      WHERE r.req_identifier = 'ZZ-REQ-1'
      GROUP BY r.program_id, r.req_id, r.req_identifier, r.title, r.req_type
   ) cov;
   PERFORM assert_equals('program_consistency',
      'W01 — same requirement code in two programs yields two coverage rows', 2::BIGINT, v_count);
   PERFORM assert_equals('program_consistency',
      'W02 — exactly one of the two is covered', 1::BIGINT, v_covered);
   PERFORM assert_equals('program_consistency',
      'W03 — the other is reported as NO COVERAGE', 1::BIGINT, v_uncov);

-- ─────────────────────────────────────────────────────────────────────────────
-- Cleanup: remove the fixture. Defects and results go first: neither FK
-- (defect -> result, result -> test case) cascades.
-- ─────────────────────────────────────────────────────────────────────────────
   DELETE FROM defect_reports WHERE defect_ref LIKE 'ZZ-DR-%';
   DELETE FROM test_results   WHERE result_id = v_res_a;
   DELETE FROM test_programs  WHERE program_id IN (v_prog_a, v_prog_b);

   SELECT COUNT(*) INTO v_count FROM test_phases WHERE phase_id IN (v_ph_a, v_ph_b);
   PERFORM assert_equals('program_consistency',
      'X01 — fixture removed (cascade from programs)', 0::BIGINT, v_count);
END;
$$;
