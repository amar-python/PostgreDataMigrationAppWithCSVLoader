-- =============================================================================
-- TEST SUITE: REQUIREMENTS & VCRM COVERAGE
-- File: tests/suites/test_03_requirements_vcrm.sql
-- =============================================================================

\echo '   [suite 03] requirements & VCRM coverage'

DO
$$
DECLARE
   v_count     BIGINT;
   v_value     TEXT;
   v_pct       NUMERIC;
BEGIN

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION I: REQUIREMENTS — Seed data & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- I01: correct row count
   SELECT COUNT(*) INTO v_count FROM requirements;
   PERFORM assert_equals(
      'requirements', 'I01 — Row count = 8',
      8::BIGINT, v_count
   );

   -- I02: CYB9131 has 6 requirements
   SELECT COUNT(*) INTO v_count
   FROM requirements r
   JOIN test_programs tp ON tp.program_id = r.program_id
   WHERE tp.program_code = 'CYB9131';
   PERFORM assert_equals(
      'requirements', 'I02 — CYB9131 has 6 requirements',
      6::BIGINT, v_count
   );

   -- I03: LAND400-P3 has 2 requirements
   SELECT COUNT(*) INTO v_count
   FROM requirements r
   JOIN test_programs tp ON tp.program_id = r.program_id
   WHERE tp.program_code = 'LAND400-P3';
   PERFORM assert_equals(
      'requirements', 'I03 — LAND400-P3 has 2 requirements',
      2::BIGINT, v_count
   );

   -- I04: all req_identifiers follow expected non-empty format
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE req_identifier IS NULL OR LENGTH(TRIM(req_identifier)) = 0;
   PERFORM assert_equals(
      'requirements', 'I04 — All requirements have a non-empty req_identifier',
      0::BIGINT, v_count
   );

   -- I05: all mandatory (priority=1) requirements have verification_method set
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE priority = 1 AND verification_method IS NULL;
   PERFORM assert_equals(
      'requirements', 'I05 — All mandatory requirements have a verification method',
      0::BIGINT, v_count
   );

   -- I06: verification_method values are within allowed set
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE verification_method NOT IN ('test','analysis','inspection','demonstration');
   PERFORM assert_equals(
      'requirements', 'I06 — All verification_method values are valid',
      0::BIGINT, v_count
   );

   -- I07: req_type values are within allowed set
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE req_type NOT IN ('functional','performance','security',
                          'safety','interface','compliance');
   PERFORM assert_equals(
      'requirements', 'I07 — All req_type values are valid',
      0::BIGINT, v_count
   );

   -- I08: priority values are between 1 and 3
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE priority NOT BETWEEN 1 AND 3;
   PERFORM assert_equals(
      'requirements', 'I08 — All priority values are between 1 and 3',
      0::BIGINT, v_count
   );

   -- I09: req_identifier + program_id is unique
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT program_id, req_identifier FROM requirements
      GROUP BY program_id, req_identifier HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'requirements', 'I09 — No duplicate req_identifier per program (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- I10: all requirements are linked to an existing program (FK integrity)
   SELECT COUNT(*) INTO v_count
   FROM requirements r
   WHERE NOT EXISTS (
      SELECT 1 FROM test_programs tp
      WHERE tp.program_id = r.program_id
   );
   PERFORM assert_equals(
      'requirements', 'I10 — All requirements reference a valid program (FK check)',
      0::BIGINT, v_count
   );

   -- I11: mandatory security requirement SYS-SEC-001 exists
   SELECT COUNT(*) INTO v_count
   FROM requirements
   WHERE req_identifier = 'SYS-SEC-001';
   PERFORM assert_equals(
      'requirements', 'I11 — SYS-SEC-001 (MFA Enforcement) requirement exists',
      1::BIGINT, v_count
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION J: REQUIREMENTS — Constraint enforcement
-- ─────────────────────────────────────────────────────────────────────────────

   -- J01: reject priority outside 1–3
   PERFORM assert_raises(
      'requirements', 'J01 — Priority outside 1–3 rejected by CHECK constraint',
      'INSERT INTO ' || current_setting('te.schema_name') || '.' || 'requirements' ||
      $q$ (program_id, req_identifier, title, priority, verification_method)
          SELECT program_id, 'SYS-BAD-999', 'Bad Priority Test', 9, 'test'
          FROM $q$ || current_setting('te.schema_name') || '.' || 'test_programs' ||
      ' LIMIT 1'
   );

   -- J02: reject invalid verification_method
   PERFORM assert_raises(
      'requirements', 'J02 — Invalid verification_method rejected by CHECK',
      'INSERT INTO ' || current_setting('te.schema_name') || '.' || 'requirements' ||
      $q$ (program_id, req_identifier, title, priority, verification_method)
          SELECT program_id, 'SYS-BAD-888', 'Bad Method Test', 1, 'guess'
          FROM $q$ || current_setting('te.schema_name') || '.' || 'test_programs' ||
      ' LIMIT 1'
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION K: VCRM — Coverage completeness & integrity
-- ─────────────────────────────────────────────────────────────────────────────

   -- K01: correct row count in vcrm_entries
   SELECT COUNT(*) INTO v_count FROM vcrm_entries;
   PERFORM assert_equals(
      'vcrm', 'K01 — VCRM row count = 8',
      8::BIGINT, v_count
   );

   -- K02: all CYB9131 requirements have at least one test case mapped
   SELECT COUNT(*) INTO v_count
   FROM requirements r
   JOIN test_programs tp ON tp.program_id = r.program_id
   WHERE tp.program_code = 'CYB9131'
   AND NOT EXISTS (
      SELECT 1 FROM vcrm_entries v
      WHERE v.req_id = r.req_id
   );
   PERFORM assert_equals(
      'vcrm', 'K02 — All CYB9131 requirements have VCRM coverage',
      0::BIGINT, v_count
   );

   -- K03: SYS-SEC-001 (MFA) is covered by exactly 2 test cases
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries v
   JOIN requirements r ON r.req_id = v.req_id
   WHERE r.req_identifier = 'SYS-SEC-001';
   PERFORM assert_equals(
      'vcrm', 'K03 — SYS-SEC-001 (MFA) mapped to exactly 2 test cases',
      2::BIGINT, v_count
   );

   -- K04: SYS-PERF-001 (Availability SLA) is covered by exactly 1 test case
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries v
   JOIN requirements r ON r.req_id = v.req_id
   WHERE r.req_identifier = 'SYS-PERF-001';
   PERFORM assert_equals(
      'vcrm', 'K04 — SYS-PERF-001 (Availability) mapped to exactly 1 test case',
      1::BIGINT, v_count
   );

   -- K05: no duplicate req+tc pairs in VCRM
   SELECT COUNT(*) INTO v_count
   FROM (
      SELECT req_id, tc_id FROM vcrm_entries
      GROUP BY req_id, tc_id HAVING COUNT(*) > 1
   ) dups;
   PERFORM assert_equals(
      'vcrm', 'K05 — No duplicate req↔tc entries in VCRM (UNIQUE enforced)',
      0::BIGINT, v_count
   );

   -- K06: all VCRM entries reference a valid requirement (FK integrity)
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries v
   WHERE NOT EXISTS (
      SELECT 1 FROM requirements r
      WHERE r.req_id = v.req_id
   );
   PERFORM assert_equals(
      'vcrm', 'K06 — All VCRM entries reference a valid requirement (FK check)',
      0::BIGINT, v_count
   );

   -- K07: all VCRM entries reference a valid test case (FK integrity)
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries v
   WHERE NOT EXISTS (
      SELECT 1 FROM test_cases tc
      WHERE tc.tc_id = v.tc_id
   );
   PERFORM assert_equals(
      'vcrm', 'K07 — All VCRM entries reference a valid test case (FK check)',
      0::BIGINT, v_count
   );

   -- K08: coverage_type values are within the allowed set
   SELECT COUNT(*) INTO v_count
   FROM vcrm_entries
   WHERE coverage_type NOT IN ('full','partial','conditional');
   PERFORM assert_equals(
      'vcrm', 'K08 — All coverage_type values are valid',
      0::BIGINT, v_count
   );

   -- K09: LAND400 requirements have NO VCRM coverage yet (expected gap)
   SELECT COUNT(*) INTO v_count
   FROM requirements r
   JOIN test_programs tp ON tp.program_id = r.program_id
   WHERE tp.program_code = 'LAND400-P3'
   AND EXISTS (
      SELECT 1 FROM vcrm_entries v
      WHERE v.req_id = r.req_id
   );
   PERFORM assert_equals(
      'vcrm', 'K09 — LAND400-P3 requirements correctly have no VCRM entries yet',
      0::BIGINT, v_count
   );

   -- K10: overall VCRM coverage rate for CYB9131 is 100%
   SELECT
      ROUND(
         100.0 * COUNT(DISTINCT v.req_id) /
         NULLIF(COUNT(DISTINCT r.req_id), 0), 1
      ) INTO v_pct
   FROM requirements r
   JOIN test_programs tp ON tp.program_id = r.program_id
   LEFT JOIN vcrm_entries v ON v.req_id = r.req_id
   WHERE tp.program_code = 'CYB9131';

   PERFORM assert_equals(
      'vcrm', 'K10 — CYB9131 VCRM coverage is 100%',
      100.0::NUMERIC, v_pct
   );

END;
$$;
