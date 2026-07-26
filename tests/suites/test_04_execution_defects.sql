-- =============================================================================
-- TEST SUITE: TEST CASES, EVENTS, RESULTS & DEFECT REPORTS
-- File: tests/suites/test_04_execution_defects.sql
-- =============================================================================

\echo '   [suite 04] test cases, events, results & defect reports'

DO
$$
DECLARE
   v_count   BIGINT;
   v_value   TEXT;
BEGIN

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION L: TEST CASES — Seed data & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- L01: correct row count
   SELECT COUNT(*) INTO v_count FROM test_cases;
   PERFORM assert_equals(
      'test_cases', 'L01 — Row count = 8',
      8::BIGINT, v_count
   );

   -- L02: all test cases linked to the CYB9131 OT&E phase
   SELECT COUNT(*) INTO v_count
   FROM test_cases tc
   JOIN test_phases ph ON ph.phase_id = tc.phase_id
   WHERE ph.phase_code = 'CYB9131-OTE';
   PERFORM assert_equals(
      'test_cases', 'L02 — All 8 test cases belong to CYB9131 OT&E phase',
      8::BIGINT, v_count
   );

   -- L03: all test cases have status = 'approved'
   SELECT COUNT(*) INTO v_count
   FROM test_cases
   WHERE status != 'approved';
   PERFORM assert_equals(
      'test_cases', 'L03 — All seeded test cases are in approved status',
      0::BIGINT, v_count
   );

   -- L04: TC-OTE-001 (MFA positive) exists
   SELECT COUNT(*) INTO v_count
   FROM test_cases
   WHERE tc_identifier = 'TC-OTE-001';
   PERFORM assert_equals(
      'test_cases', 'L04 — TC-OTE-001 (MFA valid TOTP) exists',
      1::BIGINT, v_count
   );

   -- L05: all test cases have a non-empty title
   SELECT COUNT(*) INTO v_count
   FROM test_cases
   WHERE title IS NULL OR LENGTH(TRIM(title)) = 0;
   PERFORM assert_equals(
      'test_cases', 'L05 — All test cases have a non-empty title',
      0::BIGINT, v_count
   );

   -- L06: all tc_type values are within the allowed set
   SELECT COUNT(*) INTO v_count
   FROM test_cases
   WHERE tc_type NOT IN ('functional','performance','security',
                         'regression','integration','acceptance');
   PERFORM assert_equals(
      'test_cases', 'L06 — All tc_type values are valid',
      0::BIGINT, v_count
   );

   -- L07: all test cases have an author in the personnel table
   SELECT COUNT(*) INTO v_count
   FROM test_cases tc
   WHERE NOT EXISTS (
      SELECT 1 FROM personnel p
      WHERE p.person_id = tc.author_id
   );
   PERFORM assert_equals(
      'test_cases', 'L07 — All test case authors exist in personnel (FK check)',
      0::BIGINT, v_count
   );

   -- L08: tc_identifier + phase_id is unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT phase_id, tc_identifier FROM test_cases
      GROUP BY phase_id, tc_identifier HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'test_cases', 'L08 — No duplicate tc_identifier per phase (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- L09: all test cases have a defined objective
   SELECT COUNT(*) INTO v_count
   FROM test_cases
   WHERE objective IS NULL OR LENGTH(TRIM(objective)) = 0;
   PERFORM assert_equals(
      'test_cases', 'L09 — All test cases have a defined objective',
      0::BIGINT, v_count
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION M: TEST EVENTS — Seed data & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- M01: correct row count
   SELECT COUNT(*) INTO v_count FROM test_events;
   PERFORM assert_equals(
      'test_events', 'M01 — Row count = 3',
      3::BIGINT, v_count
   );

   -- M02: event codes are unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT event_code FROM test_events
      GROUP BY event_code HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'test_events', 'M02 — All event_codes are unique (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- M03: EV01 is completed
   SELECT status INTO v_value
   FROM test_events
   WHERE event_code = 'CYB9131-OTE-EV01';
   PERFORM assert_equals(
      'test_events', 'M03 — CYB9131-OTE-EV01 status is completed',
      'completed', v_value
   );

   -- M04: EV02 is in_progress
   SELECT status INTO v_value
   FROM test_events
   WHERE event_code = 'CYB9131-OTE-EV02';
   PERFORM assert_equals(
      'test_events', 'M04 — CYB9131-OTE-EV02 status is in_progress',
      'in_progress', v_value
   );

   -- M05: EV03 is planned (future)
   SELECT status INTO v_value
   FROM test_events
   WHERE event_code = 'CYB9131-OTE-EV03';
   PERFORM assert_equals(
      'test_events', 'M05 — CYB9131-OTE-EV03 status is planned',
      'planned', v_value
   );

   -- M06: completed events have both actual_start and actual_end populated
   SELECT COUNT(*) INTO v_count
   FROM test_events
   WHERE status = 'completed'
   AND (actual_start IS NULL OR actual_end IS NULL);
   PERFORM assert_equals(
      'test_events', 'M06 — All completed events have actual_start and actual_end',
      0::BIGINT, v_count
   );

   -- M07: planned events have no actual_end date
   SELECT COUNT(*) INTO v_count
   FROM test_events
   WHERE status = 'planned' AND actual_end IS NOT NULL;
   PERFORM assert_equals(
      'test_events', 'M07 — Planned events have no actual_end date',
      0::BIGINT, v_count
   );

   -- M08: all events are linked to a valid phase (FK check)
   SELECT COUNT(*) INTO v_count
   FROM test_events ev
   WHERE NOT EXISTS (
      SELECT 1 FROM test_phases ph
      WHERE ph.phase_id = ev.phase_id
   );
   PERFORM assert_equals(
      'test_events', 'M08 — All test events reference a valid phase (FK check)',
      0::BIGINT, v_count
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION N: TEST RESULTS — Seed data & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- N01: correct row count
   SELECT COUNT(*) INTO v_count FROM test_results;
   PERFORM assert_equals(
      'test_results', 'N01 — Row count = 7',
      7::BIGINT, v_count
   );

   -- N02: Event 1 has 6 results
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events ev ON ev.event_id = tr.event_id
   WHERE ev.event_code = 'CYB9131-OTE-EV01';
   PERFORM assert_equals(
      'test_results', 'N02 — EV01 has 6 test results',
      6::BIGINT, v_count
   );

   -- N03: Event 2 has 1 result (in-progress)
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events ev ON ev.event_id = tr.event_id
   WHERE ev.event_code = 'CYB9131-OTE-EV02';
   PERFORM assert_equals(
      'test_results', 'N03 — EV02 has 1 test result so far',
      1::BIGINT, v_count
   );

   -- N04: EV01 produced 4 passes
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events ev ON ev.event_id = tr.event_id
   WHERE ev.event_code = 'CYB9131-OTE-EV01'
   AND   tr.verdict = 'pass';
   PERFORM assert_equals(
      'test_results', 'N04 — EV01 has 4 pass verdicts',
      4::BIGINT, v_count
   );

   -- N05: EV01 produced 2 fails
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events ev ON ev.event_id = tr.event_id
   WHERE ev.event_code = 'CYB9131-OTE-EV01'
   AND   tr.verdict = 'fail';
   PERFORM assert_equals(
      'test_results', 'N05 — EV01 has 2 fail verdicts',
      2::BIGINT, v_count
   );

   -- N06: EV02 result is inconclusive (72-hour test still running)
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   JOIN test_events ev ON ev.event_id = tr.event_id
   WHERE ev.event_code = 'CYB9131-OTE-EV02'
   AND   tr.verdict = 'inconclusive';
   PERFORM assert_equals(
      'test_results', 'N06 — EV02 result verdict is inconclusive',
      1::BIGINT, v_count
   );

   -- N07: verdict values are all within allowed set
   SELECT COUNT(*) INTO v_count
   FROM test_results
   WHERE verdict NOT IN ('pass','fail','blocked','not_run','inconclusive');
   PERFORM assert_equals(
      'test_results', 'N07 — All verdict values are valid',
      0::BIGINT, v_count
   );

   -- N08: all results reference a valid test case (FK check)
   SELECT COUNT(*) INTO v_count
   FROM test_results tr
   WHERE NOT EXISTS (
      SELECT 1 FROM test_cases tc
      WHERE tc.tc_id = tr.tc_id
   );
   PERFORM assert_equals(
      'test_results', 'N08 — All test results reference a valid test case (FK check)',
      0::BIGINT, v_count
   );

   -- N09: all results have an actual_result or notes documented
   SELECT COUNT(*) INTO v_count
   FROM test_results
   WHERE actual_result IS NULL AND notes IS NULL;
   PERFORM assert_equals(
      'test_results', 'N09 — All results have actual_result or notes recorded',
      0::BIGINT, v_count
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION O: DEFECT REPORTS — Seed data & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- O01: correct row count
   SELECT COUNT(*) INTO v_count FROM defect_reports;
   PERFORM assert_equals(
      'defect_reports', 'O01 — Row count = 3',
      3::BIGINT, v_count
   );

   -- O02: DR-CYB-0001 exists (audit log gap)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE defect_ref = 'DR-CYB-0001';
   PERFORM assert_equals(
      'defect_reports', 'O02 — DR-CYB-0001 (Audit Log gap) exists',
      1::BIGINT, v_count
   );

   -- O03: DR-CYB-0002 exists (TLS 1.2 gap)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE defect_ref = 'DR-CYB-0002';
   PERFORM assert_equals(
      'defect_reports', 'O03 — DR-CYB-0002 (TLS 1.2 gap) exists',
      1::BIGINT, v_count
   );

   -- O04: DR-CYB-0003 exists (session timeout)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE defect_ref = 'DR-CYB-0003';
   PERFORM assert_equals(
      'defect_reports', 'O04 — DR-CYB-0003 (Session Timeout) exists',
      1::BIGINT, v_count
   );

   -- O05: no critical-severity defects (all are major or minor)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE severity = 'critical';
   PERFORM assert_equals(
      'defect_reports', 'O05 — No critical-severity defects in seed data',
      0::BIGINT, v_count
   );

   -- O06: 2 major defects seeded
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE severity = 'major';
   PERFORM assert_equals(
      'defect_reports', 'O06 — 2 major-severity defects seeded',
      2::BIGINT, v_count
   );

   -- O07: no closed or resolved defects (all open or in-progress)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE status IN ('closed','resolved');
   PERFORM assert_equals(
      'defect_reports', 'O07 — No closed/resolved defects (all active)',
      0::BIGINT, v_count
   );

   -- O08: all defects reference a valid program (FK check)
   SELECT COUNT(*) INTO v_count
   FROM defect_reports dr
   WHERE NOT EXISTS (
      SELECT 1 FROM test_programs tp
      WHERE tp.program_id = dr.program_id
   );
   PERFORM assert_equals(
      'defect_reports', 'O08 — All defects reference a valid program (FK check)',
      0::BIGINT, v_count
   );

   -- O09: all defects have a raiser in personnel
   SELECT COUNT(*) INTO v_count
   FROM defect_reports dr
   WHERE NOT EXISTS (
      SELECT 1 FROM personnel p
      WHERE p.person_id = dr.raised_by_id
   );
   PERFORM assert_equals(
      'defect_reports', 'O09 — All defect raisers exist in personnel (FK check)',
      0::BIGINT, v_count
   );

   -- O10: defect_ref values are unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT defect_ref FROM defect_reports
      GROUP BY defect_ref HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'defect_reports', 'O10 — All defect_ref values are unique (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- O11: resolved defects must have a resolved_at timestamp
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE status = 'resolved' AND resolved_at IS NULL;
   PERFORM assert_equals(
      'defect_reports', 'O11 — All resolved defects have a resolved_at timestamp',
      0::BIGINT, v_count
   );

   -- O12: severity values are within allowed set
   SELECT COUNT(*) INTO v_count
   FROM defect_reports
   WHERE severity NOT IN ('critical','major','minor','observation');
   PERFORM assert_equals(
      'defect_reports', 'O12 — All severity values are valid',
      0::BIGINT, v_count
   );

END;
$$;
