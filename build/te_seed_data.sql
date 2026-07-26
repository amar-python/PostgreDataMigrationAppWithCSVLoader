-- ====
-- schema/postgresql/te_seed_data.sql — PostgreSQL T&E Seed Data
-- ====
-- Appended to the psql script by adapter_postgresql.sh when SEED=true.
-- The placeholder {{DB_NAME}} is replaced before execution.
--
-- Data mirrors the Teradata seed data for cross-engine consistency.
-- PostgreSQL differences applied here:
--   - ON CONFLICT DO NOTHING — safe to re-run without duplicate errors
--   - UUID type used for ID columns (stored as uuid, not CHAR(36))
--   - TRUE/FALSE instead of BYTEINT 1/0
--   - DATE format: '2025-01-01'::date (ISO 8601)
--   - TIMESTAMP format: '2025-01-01 00:00:00'::timestamp
--   - No COLLECT STATISTICS (use ANALYZE instead)
--   - Schema-qualified as {{DB_NAME}}.{{TBL_*}} via search_path or explicit schema
-- ====

SET search_path TO {{DB_NAME}};


-- ====
-- organisations
-- ====
INSERT INTO {{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000-0000-0000-0000-00001',
    'Capability Acquisition and Sustainment Group (CASG)',
    'government', 'AU', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000-0000-0000-0000-00002',
    'Defence Science and Technology (DST) Group',
    'government', 'AU', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000-0000-0000-0000-00003',
    'Leidos Australia',
    'prime', 'AU', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000-0000-0000-0000-00004',
    'BAE Systems Australia',
    'prime', 'AU', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000-0000-0000-0000-00005',
    'Joint Systems Test Facility (JSTF)',
    'test_unit', 'AU', TRUE)
ON CONFLICT DO NOTHING;


-- ====
-- personnel
-- NOTE: password_hash values are bcrypt placeholders — replace before production
-- ====
INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00001',
    '10000-0000-0000-0000-00001',
    'Brigadier Helen Marsh', 'h.marsh@defence.gov.au',
    'test_director', 'PV',
    '$2b$12$PLACEHOLDER_BRIG_MARSH', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00002',
    '10000-0000-0000-0000-00001',
    'Col. Patrick OBrien', 'p.obrien@defence.gov.au',
    'test_manager', 'NV2',
    '$2b$12$PLACEHOLDER_COL_OBRIEN', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00003',
    '10000-0000-0000-0000-00002',
    'Dr. Anika Sharma', 'a.sharma@dst.defence.gov.au',
    'test_engineer', 'NV2',
    '$2b$12$PLACEHOLDER_DR_SHARMA', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00004',
    '10000-0000-0000-0000-00003',
    'Marcus Tran', 'm.tran@leidos.com.au',
    'te_analyst', 'NV1',
    '$2b$12$PLACEHOLDER_TRAN', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00005',
    '10000-0000-0000-0000-00003',
    'Yasmin El-Khoury', 'y.elkhoury@leidos.com.au',
    'te_analyst', 'NV1',
    '$2b$12$PLACEHOLDER_ELKHOURY', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000-0000-0000-0000-00006',
    '10000-0000-0000-0000-00005',
    'Flt Lt Sam Burgess', 's.burgess@defence.gov.au',
    'safety_engineer', 'NV2',
    '$2b$12$PLACEHOLDER_BURGESS', TRUE)
ON CONFLICT DO NOTHING;


-- ====
-- test_programs
-- ====
INSERT INTO {{TBL_TEST_PROGRAMS}}
   (program_id, org_id, program_director_id, program_code, program_name,
    capability_area, classification, status, start_date, end_date)
VALUES
   ('30000-0000-0000-0000-00001',
    '10000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00001',
    'CYB9131',
    'COSPO Cyber OT&E Programme',
    'Cyber / Information Warfare',
    'PROTECTED', 'active',
    '2024-07-01'::date, '2026-06-30'::date)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_PROGRAMS}}
   (program_id, org_id, program_director_id, program_code, program_name,
    capability_area, classification, status, start_date, end_date)
VALUES
   ('30000-0000-0000-0000-00002',
    '10000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00001',
    'LAND400-P3',
    'LAND 400 Phase 3 - Infantry Fighting Vehicle T&E',
    'Land Combat Vehicle',
    'SECRET', 'active',
    '2024-01-15'::date, '2027-12-31'::date)
ON CONFLICT DO NOTHING;


-- ====
-- temp_documents
-- ====
INSERT INTO {{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000-0000-0000-0000-00001',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00002',
    'v1.0',
    'COSPO CYB9131 Test and Evaluation Master Plan v1.0',
    'approved',
    '/documents/CYB9131/TEMP_v1.0_APPROVED.pdf')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000-0000-0000-0000-00002',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00002',
    'v1.1',
    'COSPO CYB9131 Test and Evaluation Master Plan v1.1 (Amendment)',
    'in_review',
    '/documents/CYB9131/TEMP_v1.1_DRAFT.pdf')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000-0000-0000-0000-00003',
    '30000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00002',
    'v0.5',
    'LAND 400 Phase 3 IFV T&E Master Plan v0.5',
    'draft',
    '/documents/LAND400P3/TEMP_v0.5_DRAFT.pdf')
ON CONFLICT DO NOTHING;


-- ====
-- test_phases
-- ====
INSERT INTO {{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end, actual_start)
VALUES
   ('50000-0000-0000-0000-00001',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00002',
    'CYB9131-DTE', 'DT&E',
    'COSPO CYB9131 - Developmental Test and Evaluation',
    'completed',
    '2024-07-01'::date, '2024-12-31'::date, '2024-07-08'::date)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end, actual_start)
VALUES
   ('50000-0000-0000-0000-00002',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00002',
    'CYB9131-OTE', 'OT&E',
    'COSPO CYB9131 - Operational Test and Evaluation',
    'active',
    '2025-01-15'::date, '2025-12-31'::date, '2025-01-20'::date)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end)
VALUES
   ('50000-0000-0000-0000-00003',
    '30000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'L400P3-ATE', 'AT&E',
    'LAND 400 Ph3 IFV - Acceptance Test and Evaluation',
    'planned',
    '2025-06-01'::date, '2026-03-31'::date)
ON CONFLICT DO NOTHING;


-- ====
-- requirements
-- ====
INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00001',
    '30000-0000-0000-0000-00001',
    'SYS-SEC-001', 'Multi-Factor Authentication Enforcement',
    'security', 1, 'CYB9131 SRD v2.3 S4.1', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00002',
    '30000-0000-0000-0000-00001',
    'SYS-SEC-002', 'Data-at-Rest Encryption (AES-256)',
    'security', 1, 'CYB9131 SRD v2.3 S4.2', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00003',
    '30000-0000-0000-0000-00001',
    'SYS-PERF-001', 'System Availability - 99.5% Uptime SLA',
    'performance', 1, 'CYB9131 SRD v2.3 S5.1', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00004',
    '30000-0000-0000-0000-00001',
    'SYS-FUNC-001', 'Audit Log - All User Actions Captured',
    'functional', 1, 'CYB9131 SRD v2.3 S6.3', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00005',
    '30000-0000-0000-0000-00001',
    'SYS-FUNC-002', 'Role-Based Access Control (RBAC) Enforcement',
    'functional', 1, 'CYB9131 SRD v2.3 S6.4', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00006',
    '30000-0000-0000-0000-00001',
    'SYS-COMP-001', 'ISM Control Compliance - Section 3 (Gateways)',
    'compliance', 1, 'ACSC ISM 2024 S3', 'inspection')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00007',
    '30000-0000-0000-0000-00002',
    'IFV-PERF-001', 'Cross-Country Speed - 40 km/h Minimum',
    'performance', 1, 'LAND400 SRD v1.0 S8.2', 'test')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000-0000-0000-0000-00008',
    '30000-0000-0000-0000-00002',
    'IFV-SAF-001', 'Crew Survivability - STANAG 4569 Level 4',
    'safety', 1, 'LAND400 SRD v1.0 S9.1', 'analysis')
ON CONFLICT DO NOTHING;


-- ====
-- test_cases
-- ====
INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00001',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'TC-OTE-001', 'MFA - Valid TOTP Login Succeeds',
    'Verify system grants access when correct TOTP code is supplied.',
    'security', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00002',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'TC-OTE-002', 'MFA - Brute-Force Lockout After 5 Failures',
    'Verify account is locked after 5 consecutive incorrect TOTP codes.',
    'security', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00003',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'TC-OTE-003', 'Encryption - Verify AES-256 on Stored Data',
    'Confirm classified records are stored encrypted using AES-256.',
    'security', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00004',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00004',
    'TC-OTE-004', 'Availability - Sustained Load Over 72-Hour Window',
    'Confirm system sustains 99.5% uptime under simulated operational load.',
    'performance', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00005',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00004',
    'TC-OTE-005', 'Audit Log - Verify All Write Operations Are Captured',
    'Confirm every CREATE, UPDATE, DELETE action is recorded in the audit log.',
    'functional', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00006',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'TC-OTE-006', 'RBAC - Operator Cannot Access Admin Functions',
    'Verify operator role cannot invoke admin-only API endpoints.',
    'functional', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00007',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00005',
    'TC-OTE-007', 'ISM Compliance - Gateway Configuration Inspection',
    'Inspect gateway configuration against ACSC ISM Section 3 controls.',
    'acceptance', 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000-0000-0000-0000-00008',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00005',
    'TC-OTE-008', 'Data-in-Transit - TLS 1.3 Enforcement on All APIs',
    'Confirm all REST API endpoints enforce TLS 1.3 minimum.',
    'security', 'approved')
ON CONFLICT DO NOTHING;


-- ====
-- vcrm_entries
-- ====
INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00001',
    '60000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00001',
    'full', 'Positive path - valid TOTP grants access.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00002',
    '60000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00002',
    'full', 'Negative path - brute-force lockout enforces MFA resilience.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00003',
    '60000-0000-0000-0000-00002',
    '70000-0000-0000-0000-00003',
    'full', 'Directly verifies AES-256 applied to stored classified data.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00004',
    '60000-0000-0000-0000-00002',
    '70000-0000-0000-0000-00008',
    'partial', 'TLS-in-transit complements data-at-rest encryption coverage.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00005',
    '60000-0000-0000-0000-00003',
    '70000-0000-0000-0000-00004',
    'full', '72-hour load test directly validates the 99.5% SLA.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00006',
    '60000-0000-0000-0000-00004',
    '70000-0000-0000-0000-00005',
    'full', 'Covers all write operations in prescribed test scenarios.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00007',
    '60000-0000-0000-0000-00005',
    '70000-0000-0000-0000-00006',
    'full', 'Directly validates operator-role access restrictions.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000-0000-0000-0000-00008',
    '60000-0000-0000-0000-00006',
    '70000-0000-0000-0000-00007',
    'full', 'Inspection-based verification of all ISM S3 gateway controls.',
    '20000-0000-0000-0000-00002')
ON CONFLICT DO NOTHING;


-- ====
-- test_events
-- ====
INSERT INTO {{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end, actual_start, actual_end)
VALUES
   ('90000-0000-0000-0000-00001',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00002',
    'CYB9131-OTE-EV01',
    'COSPO OT&E Event 1 - Security and Functional Verification',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'completed',
    '2025-02-10'::date, '2025-02-14'::date,
    '2025-02-10'::date, '2025-02-14'::date)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end, actual_start)
VALUES
   ('90000-0000-0000-0000-00002',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00002',
    'CYB9131-OTE-EV02',
    'COSPO OT&E Event 2 - Performance and Endurance',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'in_progress',
    '2025-04-07'::date, '2025-04-11'::date,
    '2025-04-07'::date)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end)
VALUES
   ('90000-0000-0000-0000-00003',
    '50000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00002',
    'CYB9131-OTE-EV03',
    'COSPO OT&E Event 3 - ISM Compliance Inspection',
    'integration_test', 'JSTF Cyber Lab, Russell Offices, ACT',
    'planned',
    '2025-06-16'::date, '2025-06-20'::date)
ON CONFLICT DO NOTHING;


-- ====
-- test_results
-- ====
INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00001',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00003',
    'pass',
    '2025-02-11 09:35:00'::timestamp,
    'User authenticated in 1.8s. Session token issued.',
    'Repeated 20 times across 4 user accounts - all passed.')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00002',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00002',
    '20000-0000-0000-0000-00003',
    'pass',
    '2025-02-11 11:10:00'::timestamp,
    'Account locked on 5th failed attempt. Alert triggered.',
    'Lockout time 47ms after final failure - within spec.')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00003',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00003',
    '20000-0000-0000-0000-00004',
    'pass',
    '2025-02-12 09:00:00'::timestamp,
    'All 100 PROTECTED records confirmed encrypted (AES-256-GCM).',
    'Keys held in Azure Key Vault. Rotation schedule confirmed.')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00004',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00005',
    '20000-0000-0000-0000-00004',
    'fail',
    '2025-02-12 14:30:00'::timestamp,
    '28 of 30 write operations captured. DELETE on archive endpoint not logged.',
    'DR raised: DR-CYB-0001. Deficiency in audit hook for archive endpoint.')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00005',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00006',
    '20000-0000-0000-0000-00005',
    'pass',
    '2025-02-13 10:00:00'::timestamp,
    'All 12 admin endpoints returned HTTP 403 for operator role.',
    NULL)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00006',
    '90000-0000-0000-0000-00001',
    '70000-0000-0000-0000-00008',
    '20000-0000-0000-0000-00003',
    'fail',
    '2025-02-13 14:00:00'::timestamp,
    'Endpoint /api/v1/legacy/export accepts TLS 1.2 connections.',
    'DR raised: DR-CYB-0002. Legacy endpoint excluded from TLS policy rollout.')
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000-0000-0000-0000-00007',
    '90000-0000-0000-0000-00002',
    '70000-0000-0000-0000-00004',
    '20000-0000-0000-0000-00004',
    'inconclusive',
    '2025-04-08 08:00:00'::timestamp,
    '24 hours elapsed - uptime 99.9%. Full 72-hour window in progress.',
    'Monitoring dashboard live. Splunk alerts configured.')
ON CONFLICT DO NOTHING;


-- ====
-- defect_reports
-- ====
INSERT INTO {{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000-0000-0000-0000-00001',
    'a0000-0000-0000-0000-00004',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00004',
    '20000-0000-0000-0000-00003',
    'DR-CYB-0001',
    'Audit Log - DELETE on /api/v2/archive/ Not Captured',
    'The DELETE method on the archive endpoint does not trigger an audit log entry. Affects SYS-FUNC-001 compliance.',
    'major', 'in_progress',
    '2025-02-12 15:00:00'::timestamp)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000-0000-0000-0000-00002',
    'a0000-0000-0000-0000-00006',
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00003',
    '20000-0000-0000-0000-00003',
    'DR-CYB-0002',
    'TLS 1.2 Accepted on Legacy Export Endpoint',
    'The /api/v1/legacy/export endpoint was excluded from the TLS 1.3 policy rollout. Affects SYS-SEC-002 coverage.',
    'major', 'open',
    '2025-02-13 14:45:00'::timestamp)
ON CONFLICT DO NOTHING;

INSERT INTO {{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000-0000-0000-0000-00003',
    NULL,
    '30000-0000-0000-0000-00001',
    '20000-0000-0000-0000-00006',
    '20000-0000-0000-0000-00002',
    'DR-CYB-0003',
    'Session Timeout Not Enforced After 15-Minute Inactivity',
    'Idle sessions remain active indefinitely. ISM S6.2.4 requires automatic session termination after 15 minutes.',
    'minor', 'open',
    '2025-03-04 11:20:00'::timestamp)
ON CONFLICT DO NOTHING;


-- ====
-- evidence_artifacts — intentionally left empty (no evidence uploaded yet)
-- ====

-- ====
-- ANALYZE tables after seed data load for accurate query plans
-- (PostgreSQL equivalent of Teradata COLLECT STATISTICS)
-- ====
ANALYZE {{TBL_ORGANISATIONS}};
ANALYZE {{TBL_PERSONNEL}};
ANALYZE {{TBL_TEST_PROGRAMS}};
ANALYZE {{TBL_TEST_RESULTS}};
ANALYZE {{TBL_DEFECT_REPORTS}};