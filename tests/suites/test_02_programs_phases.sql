-- =============================================================================
-- TEST SUITE: PROGRAMS, TEMP DOCUMENTS & TEST PHASES
-- File: tests/suites/test_02_programs_phases.sql
-- =============================================================================

\echo '   [suite 02] programs, TEMP documents & test phases'

DO
$$
DECLARE
   v_count   BIGINT;
   v_value   TEXT;
   v_date1   DATE;
   v_date2   DATE;
BEGIN

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION E: TEST PROGRAMS — Seed data
-- ─────────────────────────────────────────────────────────────────────────────

   -- E01: correct row count
   SELECT COUNT(*) INTO v_count FROM test_programs;
   PERFORM assert_equals(
      'programs', 'E01 — Row count = 2',
      2::BIGINT, v_count
   );

   -- E02: CYB9131 program exists
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE program_code = 'CYB9131';
   PERFORM assert_equals(
      'programs', 'E02 — CYB9131 program present',
      1::BIGINT, v_count
   );

   -- E03: LAND400-P3 program exists
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE program_code = 'LAND400-P3';
   PERFORM assert_equals(
      'programs', 'E03 — LAND400-P3 program present',
      1::BIGINT, v_count
   );

   -- E04: all programs have a program_director assigned
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE program_director_id IS NULL;
   PERFORM assert_equals(
      'programs', 'E04 — All programs have a director assigned',
      0::BIGINT, v_count
   );

   -- E05: program directors exist in personnel table (no dangling FKs)
   SELECT COUNT(*) INTO v_count
   FROM test_programs tp
   WHERE tp.program_director_id IS NOT NULL
   AND NOT EXISTS (
      SELECT 1 FROM personnel p
      WHERE p.person_id = tp.program_director_id
   );
   PERFORM assert_equals(
      'programs', 'E05 — All program directors exist in personnel table',
      0::BIGINT, v_count
   );

   -- E06: all status values are within the allowed set
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE status NOT IN ('planning','active','suspended','completed','cancelled');
   PERFORM assert_equals(
      'programs', 'E06 — All program status values are valid',
      0::BIGINT, v_count
   );

   -- E07: classification values are all within ISM-compliant set
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE classification NOT IN ('UNCLASSIFIED','PROTECTED','SECRET','TOP SECRET');
   PERFORM assert_equals(
      'programs', 'E07 — All classification markings are valid',
      0::BIGINT, v_count
   );

   -- E08: end_date is always >= start_date (no inverted dates)
   SELECT COUNT(*) INTO v_count
   FROM test_programs
   WHERE end_date IS NOT NULL AND end_date < start_date;
   PERFORM assert_equals(
      'programs', 'E08 — No programs have end_date before start_date',
      0::BIGINT, v_count
   );

   -- E09: program_code values are unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT program_code FROM test_programs
      GROUP BY program_code HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'programs', 'E09 — All program_codes are unique',
      0::BIGINT, v_count
   );

   -- E10: CYB9131 is classified PROTECTED
   SELECT classification INTO v_value
   FROM test_programs
   WHERE program_code = 'CYB9131';
   PERFORM assert_equals(
      'programs', 'E10 — CYB9131 classification is PROTECTED',
      'PROTECTED', v_value
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION F: PROGRAMS — Constraint enforcement
-- ─────────────────────────────────────────────────────────────────────────────

   -- F01: reject inverted date range
   PERFORM assert_raises(
      'programs', 'F01 — Inverted date range rejected by CHECK constraint',
      'INSERT INTO ' || current_setting('te.schema_name') || '.' || 'test_programs' ||
      $q$ (org_id, program_code, program_name, classification, status,
           start_date, end_date)
          SELECT org_id, 'TEST-BAD-DATES', 'Bad Date Test',
                 'UNCLASSIFIED', 'planning',
                 '2025-12-31', '2025-01-01'
          FROM $q$ || current_setting('te.schema_name') || '.' || 'organisations' ||
      ' LIMIT 1'
   );

   -- F02: reject invalid classification marking
   PERFORM assert_raises(
      'programs', 'F02 — Invalid classification rejected by CHECK constraint',
      'INSERT INTO ' || current_setting('te.schema_name') || '.' || 'test_programs' ||
      $q$ (org_id, program_code, program_name, classification, status)
          SELECT org_id, 'TEST-BADCLASS', 'Bad Class Test',
                 'CONFIDENTIAL', 'planning'
          FROM $q$ || current_setting('te.schema_name') || '.' || 'organisations' ||
      ' LIMIT 1'
   );

   -- F03: reject duplicate program_code
   PERFORM assert_raises(
      'programs', 'F03 — Duplicate program_code rejected by UNIQUE constraint',
      'INSERT INTO ' || current_setting('te.schema_name') || '.' || 'test_programs' ||
      $q$ (org_id, program_code, program_name, classification, status)
          SELECT org_id, 'CYB9131', 'Duplicate Code Test',
                 'UNCLASSIFIED', 'planning'
          FROM $q$ || current_setting('te.schema_name') || '.' || 'organisations' ||
      ' LIMIT 1'
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION G: TEMP DOCUMENTS — Seed data
-- ─────────────────────────────────────────────────────────────────────────────

   -- G01: correct row count
   SELECT COUNT(*) INTO v_count FROM temp_documents;
   PERFORM assert_equals(
      'temp_documents', 'G01 — Row count = 3',
      3::BIGINT, v_count
   );

   -- G02: approved TEMP exists for CYB9131
   SELECT COUNT(*) INTO v_count
   FROM temp_documents td
   JOIN test_programs tp ON tp.program_id = td.program_id
   WHERE tp.program_code = 'CYB9131'
   AND   td.status = 'approved';
   PERFORM assert_equals(
      'temp_documents', 'G02 — CYB9131 has an approved TEMP',
      1::BIGINT, v_count
   );

   -- G03: every TEMP has an author in personnel
   SELECT COUNT(*) INTO v_count
   FROM temp_documents td
   WHERE NOT EXISTS (
      SELECT 1 FROM personnel p
      WHERE p.person_id = td.author_id
   );
   PERFORM assert_equals(
      'temp_documents', 'G03 — All TEMP authors exist in personnel',
      0::BIGINT, v_count
   );

   -- G04: version + program_id combination is unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT program_id, version FROM temp_documents
      GROUP BY program_id, version HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'temp_documents', 'G04 — No duplicate version per program (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- G05: status values are all valid
   SELECT COUNT(*) INTO v_count
   FROM temp_documents
   WHERE status NOT IN ('draft','in_review','approved','superseded','cancelled');
   PERFORM assert_equals(
      'temp_documents', 'G05 — All TEMP status values are valid',
      0::BIGINT, v_count
   );

   -- G06: at least one TEMP is in draft or in_review (active development)
   SELECT COUNT(*) INTO v_count
   FROM temp_documents
   WHERE status IN ('draft','in_review');
   PERFORM assert_true(
      'temp_documents', 'G06 — At least one TEMP in active draft/review state',
      v_count::TEXT || ' >= 1'
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION H: TEST PHASES — Seed data
-- ─────────────────────────────────────────────────────────────────────────────

   -- H01: correct row count
   SELECT COUNT(*) INTO v_count FROM test_phases;
   PERFORM assert_equals(
      'test_phases', 'H01 — Row count = 3',
      3::BIGINT, v_count
   );

   -- H02: CYB9131 has both a completed DT&E and an active OT&E phase
   SELECT COUNT(*) INTO v_count
   FROM test_phases ph
   JOIN test_programs tp ON tp.program_id = ph.program_id
   WHERE tp.program_code = 'CYB9131'
   AND   ph.phase_type IN ('DT&E','OT&E');
   PERFORM assert_equals(
      'test_phases', 'H02 — CYB9131 has DT&E and OT&E phases',
      2::BIGINT, v_count
   );

   -- H03: completed phases have an actual_start date
   SELECT COUNT(*) INTO v_count
   FROM test_phases
   WHERE status = 'completed' AND actual_start IS NULL;
   PERFORM assert_equals(
      'test_phases', 'H03 — All completed phases have an actual_start date',
      0::BIGINT, v_count
   );

   -- H04: phase_type values are within the allowed set
   SELECT COUNT(*) INTO v_count
   FROM test_phases
   WHERE phase_type NOT IN ('DT&E','AT&E','OT&E','IOT&E','LFT&E','FOLLOW_ON');
   PERFORM assert_equals(
      'test_phases', 'H04 — All phase_type values are valid',
      0::BIGINT, v_count
   );

   -- H05: phase_code + program_id is unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT program_id, phase_code FROM test_phases
      GROUP BY program_id, phase_code HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'test_phases', 'H05 — No duplicate phase_code per program (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- H06: planned phases have no actual_start date yet
   SELECT COUNT(*) INTO v_count
   FROM test_phases
   WHERE status = 'planned' AND actual_start IS NOT NULL;
   PERFORM assert_equals(
      'test_phases', 'H06 — Planned phases have no actual_start date',
      0::BIGINT, v_count
   );

END;
$$;
