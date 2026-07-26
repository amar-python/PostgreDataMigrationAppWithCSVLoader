-- =============================================================================
-- TEST SUITE: ORGANISATIONS & PERSONNEL
-- File: tests/suites/test_01_organisations_personnel.sql
-- =============================================================================

\echo '   [suite 01] organisations & personnel'

DO
$$
DECLARE
   v_count   BIGINT;
   v_value   TEXT;
   v_bool    BOOLEAN;
   v_schema  TEXT := current_setting('te.schema_name');
BEGIN

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION A: ORGANISATIONS — Seed data presence
-- ─────────────────────────────────────────────────────────────────────────────

   -- A01: correct row count
   SELECT COUNT(*) INTO v_count FROM organisations;
   PERFORM assert_equals('organisations', 'A01 — Row count = 5', 5::BIGINT, v_count);

   -- A02: CASG exists
   SELECT COUNT(*) INTO v_count
   FROM organisations WHERE name ILIKE '%Capability Acquisition%';
   PERFORM assert_equals('organisations', 'A02 — CASG record exists', 1::BIGINT, v_count);

   -- A03: all records are active by default
   SELECT COUNT(*) INTO v_count FROM organisations WHERE is_active = FALSE;
   PERFORM assert_equals('organisations', 'A03 — All organisations active by default', 0::BIGINT, v_count);

   -- A04: all country codes are exactly 2 characters
   SELECT COUNT(*) INTO v_count FROM organisations WHERE LENGTH(country) != 2;
   PERFORM assert_equals('organisations', 'A04 — All country codes are 2 chars (ISO 3166-1)', 0::BIGINT, v_count);

   -- A05: all org_type values are within allowed set
   SELECT COUNT(*) INTO v_count
   FROM organisations
   WHERE org_type NOT IN ('government','prime','subcontractor','test_unit','academic');
   PERFORM assert_equals('organisations', 'A05 — All org_type values are valid', 0::BIGINT, v_count);

   -- A06: no duplicate org names
   SELECT COUNT(*) INTO v_count
   FROM (SELECT name FROM organisations GROUP BY name HAVING COUNT(*) > 1) dups;
   PERFORM assert_equals('organisations', 'A06 — No duplicate organisation names', 0::BIGINT, v_count);

   -- A07: at least one test_unit type exists
   SELECT COUNT(*) INTO v_count FROM organisations WHERE org_type = 'test_unit';
   PERFORM assert_true('organisations', 'A07 — At least one test_unit organisation exists',
      v_count::TEXT || ' >= 1');

   -- A08: created_at is populated on all rows
   SELECT COUNT(*) INTO v_count FROM organisations WHERE created_at IS NULL;
   PERFORM assert_equals('organisations', 'A08 — created_at populated on all organisations', 0::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION B: ORGANISATIONS — Constraint enforcement
-- ─────────────────────────────────────────────────────────────────────────────

   -- B01: reject invalid org_type
   PERFORM assert_raises(
      'organisations', 'B01 — Invalid org_type rejected by CHECK constraint',
      'INSERT INTO ' || v_schema || '.organisations' ||
      ' (name, org_type, country) VALUES (''Test Org'', ''invalid_type'', ''AU'')'
   );

   -- B02: reject null name
   PERFORM assert_raises(
      'organisations', 'B02 — NULL name rejected by NOT NULL constraint',
      'INSERT INTO ' || v_schema || '.organisations' ||
      ' (name, org_type, country) VALUES (NULL, ''government'', ''AU'')'
   );

   -- B03: reject duplicate name (UNIQUE)
   PERFORM assert_raises(
      'organisations', 'B03 — Duplicate org name rejected by UNIQUE constraint',
      'INSERT INTO ' || v_schema || '.organisations' ||
      ' (name, org_type, country) VALUES (''Leidos Australia'', ''prime'', ''AU'')'
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION C: PERSONNEL — Seed data presence
-- ─────────────────────────────────────────────────────────────────────────────

   -- C01: correct row count
   SELECT COUNT(*) INTO v_count FROM personnel;
   PERFORM assert_equals('personnel', 'C01 — Row count = 6', 6::BIGINT, v_count);

   -- C02: every person is linked to a valid organisation (no orphans)
   SELECT COUNT(*) INTO v_count
   FROM personnel p WHERE NOT EXISTS (SELECT 1 FROM organisations o WHERE o.org_id = p.org_id);
   PERFORM assert_equals('personnel', 'C02 — No orphaned personnel (all linked to valid org)', 0::BIGINT, v_count);

   -- C03: at least one NV2-cleared engineer
   SELECT COUNT(*) INTO v_count FROM personnel WHERE clearance = 'NV2';
   PERFORM assert_true('personnel', 'C03 — At least one NV2-cleared person exists',
      v_count::TEXT || ' >= 1');

   -- C04: no clearance values outside allowed set
   SELECT COUNT(*) INTO v_count
   FROM personnel WHERE clearance NOT IN ('baseline','NV1','NV2','PV');
   PERFORM assert_equals('personnel', 'C04 — All clearance values are within allowed set', 0::BIGINT, v_count);

   -- C05: all email addresses contain an '@' symbol
   SELECT COUNT(*) INTO v_count FROM personnel WHERE email NOT LIKE '%@%';
   PERFORM assert_equals('personnel', 'C05 — All emails contain @', 0::BIGINT, v_count);

   -- C06: all emails are unique
   SELECT COUNT(*) INTO v_count
   FROM (SELECT email FROM personnel GROUP BY email HAVING COUNT(*) > 1) dups;
   PERFORM assert_equals('personnel', 'C06 — No duplicate email addresses', 0::BIGINT, v_count);

   -- C07: no plaintext passwords stored (all hashes must start with $2b$)
   SELECT COUNT(*) INTO v_count
   FROM personnel WHERE password_hash NOT LIKE '$2b$%' AND password_hash NOT LIKE '$2a$%';
   PERFORM assert_equals('personnel', 'C07 — All password hashes are bcrypt format ($2b$/$2a$)', 0::BIGINT, v_count);

   -- C08: te_role values are all within allowed set
   SELECT COUNT(*) INTO v_count
   FROM personnel
   WHERE te_role NOT IN (
      'test_director','test_manager','test_engineer',
      'te_analyst','safety_engineer','config_manager','observer'
   );
   PERFORM assert_equals('personnel', 'C08 — All te_role values are valid', 0::BIGINT, v_count);

   -- C09: all are active by default
   SELECT COUNT(*) INTO v_count FROM personnel WHERE is_active = FALSE;
   PERFORM assert_equals('personnel', 'C09 — All personnel active by default', 0::BIGINT, v_count);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION D: PERSONNEL — Constraint enforcement
-- ─────────────────────────────────────────────────────────────────────────────

   -- D01: reject invalid clearance level
   PERFORM assert_raises(
      'personnel', 'D01 — Invalid clearance level rejected by CHECK',
      'INSERT INTO ' || v_schema || '.personnel' ||
      $q$ (org_id, full_name, email, te_role, clearance, password_hash)
          SELECT org_id, 'Test Person', 'test.unique@test.com',
                 'te_analyst', 'TOP_SECRET', '$2b$12$hash'
          FROM $q$ || v_schema || '.organisations LIMIT 1'
   );

   -- D02: reject invalid te_role
   PERFORM assert_raises(
      'personnel', 'D02 — Invalid te_role rejected by CHECK',
      'INSERT INTO ' || v_schema || '.personnel' ||
      $q$ (org_id, full_name, email, te_role, clearance, password_hash)
          SELECT org_id, 'Test Person', 'test2.unique@test.com',
                 'super_admin', 'NV1', '$2b$12$hash'
          FROM $q$ || v_schema || '.organisations LIMIT 1'
   );

   -- D03: reject personnel with non-existent org_id (FK violation)
   PERFORM assert_raises(
      'personnel', 'D03 — Invalid org_id rejected by FK constraint',
      'INSERT INTO ' || v_schema || '.personnel' ||
      $q$ (org_id, full_name, email, te_role, clearance, password_hash)
          VALUES ('00000000-dead-beef-0000-000000000099',
                  'Ghost Person', 'ghost@test.com',
                  'te_analyst', 'NV1', '$2b$12$hash') $q$
   );

END;
$$;
