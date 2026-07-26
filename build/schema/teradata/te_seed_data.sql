-- =============================================================================
-- schema/teradata/te_seed_data.sql — Teradata Vantage T&E Seed Data
-- =============================================================================
-- Appended to the BTEQ script by adapter_teradata.sh when SEED=true.
-- The placeholder {{DB_NAME}} is replaced before execution.
--
-- Data mirrors the PostgreSQL seed data for cross-engine consistency.
-- Teradata differences applied here:
--   - No ON CONFLICT — data is inserted fresh after DROP/CREATE cycle
--   - CHAR(36) UUIDs stored as plain strings
--   - BYTEINT 1/0 instead of TRUE/FALSE
--   - DATE format: DATE '2025-01-01' (ANSI syntax)
--   - TIMESTAMP format: TIMESTAMP '2025-01-01 00:00:00'
-- =============================================================================

DATABASE {{DB_NAME}};


-- =============================================================================
-- organisations
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000000-0000-0000-0000-000000000001',
    'Capability Acquisition and Sustainment Group (CASG)',
    'government', 'AU', 1);

INSERT INTO {{DB_NAME}}.{{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000000-0000-0000-0000-000000000002',
    'Defence Science and Technology (DST) Group',
    'government', 'AU', 1);

INSERT INTO {{DB_NAME}}.{{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000000-0000-0000-0000-000000000003',
    'Leidos Australia',
    'prime', 'AU', 1);

INSERT INTO {{DB_NAME}}.{{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000000-0000-0000-0000-000000000004',
    'BAE Systems Australia',
    'prime', 'AU', 1);

INSERT INTO {{DB_NAME}}.{{TBL_ORGANISATIONS}}
   (org_id, name, org_type, country, is_active)
VALUES
   ('10000000-0000-0000-0000-000000000005',
    'Joint Systems Test Facility (JSTF)',
    'test_unit', 'AU', 1);


-- =============================================================================
-- personnel
-- NOTE: password_hash values are bcrypt placeholders — replace before production
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'Brigadier Helen Marsh', 'h.marsh@defence.gov.au',
    'test_director', 'PV',
    '$2b$12$PLACEHOLDER_BRIG_MARSH', 1);

INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'Col. Patrick OBrien', 'p.obrien@defence.gov.au',
    'test_manager', 'NV2',
    '$2b$12$PLACEHOLDER_COL_OBRIEN', 1);

INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    'Dr. Anika Sharma', 'a.sharma@dst.defence.gov.au',
    'test_engineer', 'NV2',
    '$2b$12$PLACEHOLDER_DR_SHARMA', 1);

INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    'Marcus Tran', 'm.tran@leidos.com.au',
    'te_analyst', 'NV1',
    '$2b$12$PLACEHOLDER_TRAN', 1);

INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000003',
    'Yasmin El-Khoury', 'y.elkhoury@leidos.com.au',
    'te_analyst', 'NV1',
    '$2b$12$PLACEHOLDER_ELKHOURY', 1);

INSERT INTO {{DB_NAME}}.{{TBL_PERSONNEL}}
   (person_id, org_id, full_name, email, te_role, clearance, password_hash, is_active)
VALUES
   ('20000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000005',
    'Flt Lt Sam Burgess', 's.burgess@defence.gov.au',
    'safety_engineer', 'NV2',
    '$2b$12$PLACEHOLDER_BURGESS', 1);


-- =============================================================================
-- test_programs
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEST_PROGRAMS}}
   (program_id, org_id, program_director_id, program_code, program_name,
    capability_area, classification, status, start_date, end_date)
VALUES
   ('30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'CYB9131',
    'COSPO Cyber OT&E Programme',
    'Cyber / Information Warfare',
    'PROTECTED', 'active',
    DATE '2024-07-01', DATE '2026-06-30');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_PROGRAMS}}
   (program_id, org_id, program_director_id, program_code, program_name,
    capability_area, classification, status, start_date, end_date)
VALUES
   ('30000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'LAND400-P3',
    'LAND 400 Phase 3 - Infantry Fighting Vehicle T&E',
    'Land Combat Vehicle',
    'SECRET', 'active',
    DATE '2024-01-15', DATE '2027-12-31');


-- =============================================================================
-- temp_documents
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'v1.0',
    'COSPO CYB9131 Test and Evaluation Master Plan v1.0',
    'approved',
    '/documents/CYB9131/TEMP_v1.0_APPROVED.pdf');

INSERT INTO {{DB_NAME}}.{{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'v1.1',
    'COSPO CYB9131 Test and Evaluation Master Plan v1.1 (Amendment)',
    'in_review',
    '/documents/CYB9131/TEMP_v1.1_DRAFT.pdf');

INSERT INTO {{DB_NAME}}.{{TBL_TEMP_DOCUMENTS}}
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'v0.5',
    'LAND 400 Phase 3 IFV T&E Master Plan v0.5',
    'draft',
    '/documents/LAND400P3/TEMP_v0.5_DRAFT.pdf');


-- =============================================================================
-- test_phases
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end, actual_start)
VALUES
   ('50000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-DTE', 'DT&E',
    'COSPO CYB9131 - Developmental Test and Evaluation',
    'completed',
    DATE '2024-07-01', DATE '2024-12-31', DATE '2024-07-08');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end, actual_start)
VALUES
   ('50000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE', 'OT&E',
    'COSPO CYB9131 - Operational Test and Evaluation',
    'active',
    DATE '2025-01-15', DATE '2025-12-31', DATE '2025-01-20');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_PHASES}}
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end)
VALUES
   ('50000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'L400P3-ATE', 'AT&E',
    'LAND 400 Ph3 IFV - Acceptance Test and Evaluation',
    'planned',
    DATE '2025-06-01', DATE '2026-03-31');


-- =============================================================================
-- requirements
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    'SYS-SEC-001', 'Multi-Factor Authentication Enforcement',
    'security', 1, 'CYB9131 SRD v2.3 S4.1', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    'SYS-SEC-002', 'Data-at-Rest Encryption (AES-256)',
    'security', 1, 'CYB9131 SRD v2.3 S4.2', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000001',
    'SYS-PERF-001', 'System Availability - 99.5% Uptime SLA',
    'performance', 1, 'CYB9131 SRD v2.3 S5.1', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000001',
    'SYS-FUNC-001', 'Audit Log - All User Actions Captured',
    'functional', 1, 'CYB9131 SRD v2.3 S6.3', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000005',
    '30000000-0000-0000-0000-000000000001',
    'SYS-FUNC-002', 'Role-Based Access Control (RBAC) Enforcement',
    'functional', 1, 'CYB9131 SRD v2.3 S6.4', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000006',
    '30000000-0000-0000-0000-000000000001',
    'SYS-COMP-001', 'ISM Control Compliance - Section 3 (Gateways)',
    'compliance', 1, 'ACSC ISM 2024 S3', 'inspection');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000007',
    '30000000-0000-0000-0000-000000000002',
    'IFV-PERF-001', 'Cross-Country Speed - 40 km/h Minimum',
    'performance', 1, 'LAND400 SRD v1.0 S8.2', 'test');

INSERT INTO {{DB_NAME}}.{{TBL_REQUIREMENTS}}
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000008',
    '30000000-0000-0000-0000-000000000002',
    'IFV-SAF-001', 'Crew Survivability - STANAG 4569 Level 4',
    'safety', 1, 'LAND400 SRD v1.0 S9.1', 'analysis');


-- =============================================================================
-- test_cases
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-001', 'MFA - Valid TOTP Login Succeeds',
    'Verify system grants access when correct TOTP code is supplied.',
    'security', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-002', 'MFA - Brute-Force Lockout After 5 Failures',
    'Verify account is locked after 5 consecutive incorrect TOTP codes.',
    'security', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000003',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-003', 'Encryption - Verify AES-256 on Stored Data',
    'Confirm classified records are stored encrypted using AES-256.',
    'security', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000004',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000004',
    'TC-OTE-004', 'Availability - Sustained Load Over 72-Hour Window',
    'Confirm system sustains 99.5% uptime under simulated operational load.',
    'performance', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000005',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000004',
    'TC-OTE-005', 'Audit Log - Verify All Write Operations Are Captured',
    'Confirm every CREATE, UPDATE, DELETE action is recorded in the audit log.',
    'functional', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000006',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-006', 'RBAC - Operator Cannot Access Admin Functions',
    'Verify operator role cannot invoke admin-only API endpoints.',
    'functional', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000007',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000005',
    'TC-OTE-007', 'ISM Compliance - Gateway Configuration Inspection',
    'Inspect gateway configuration against ACSC ISM Section 3 controls.',
    'acceptance', 'approved');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_CASES}}
   (tc_id, phase_id, author_id, tc_identifier, title,
    objective, tc_type, status)
VALUES
   ('70000000-0000-0000-0000-000000000008',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000005',
    'TC-OTE-008', 'Data-in-Transit - TLS 1.3 Enforcement on All APIs',
    'Confirm all REST API endpoints enforce TLS 1.3 minimum.',
    'security', 'approved');


-- =============================================================================
-- vcrm_entries
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000001',
    '60000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    'full', 'Positive path - valid TOTP grants access.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000002',
    '60000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000002',
    'full', 'Negative path - brute-force lockout enforces MFA resilience.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000003',
    '60000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000003',
    'full', 'Directly verifies AES-256 applied to stored classified data.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000004',
    '60000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000008',
    'partial', 'TLS-in-transit complements data-at-rest encryption coverage.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000005',
    '60000000-0000-0000-0000-000000000003',
    '70000000-0000-0000-0000-000000000004',
    'full', '72-hour load test directly validates the 99.5% SLA.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000006',
    '60000000-0000-0000-0000-000000000004',
    '70000000-0000-0000-0000-000000000005',
    'full', 'Covers all write operations in prescribed test scenarios.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000007',
    '60000000-0000-0000-0000-000000000005',
    '70000000-0000-0000-0000-000000000006',
    'full', 'Directly validates operator-role access restrictions.',
    '20000000-0000-0000-0000-000000000002');

INSERT INTO {{DB_NAME}}.{{TBL_VCRM_ENTRIES}}
   (vcrm_id, req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   ('80000000-0000-0000-0000-000000000008',
    '60000000-0000-0000-0000-000000000006',
    '70000000-0000-0000-0000-000000000007',
    'full', 'Inspection-based verification of all ISM S3 gateway controls.',
    '20000000-0000-0000-0000-000000000002');


-- =============================================================================
-- test_events
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end, actual_start, actual_end)
VALUES
   ('90000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV01',
    'COSPO OT&E Event 1 - Security and Functional Verification',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'completed',
    DATE '2025-02-10', DATE '2025-02-14',
    DATE '2025-02-10', DATE '2025-02-14');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end, actual_start)
VALUES
   ('90000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV02',
    'COSPO OT&E Event 2 - Performance and Endurance',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'in_progress',
    DATE '2025-04-07', DATE '2025-04-11',
    DATE '2025-04-07');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_EVENTS}}
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status,
    planned_start, planned_end)
VALUES
   ('90000000-0000-0000-0000-000000000003',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV03',
    'COSPO OT&E Event 3 - ISM Compliance Inspection',
    'integration_test', 'JSTF Cyber Lab, Russell Offices, ACT',
    'planned',
    DATE '2025-06-16', DATE '2025-06-20');


-- =============================================================================
-- test_results
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000001',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    'pass',
    TIMESTAMP '2025-02-11 09:35:00',
    'User authenticated in 1.8s. Session token issued.',
    'Repeated 20 times across 4 user accounts - all passed.');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000002',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'pass',
    TIMESTAMP '2025-02-11 11:10:00',
    'Account locked on 5th failed attempt. Alert triggered.',
    'Lockout time 47ms after final failure - within spec.');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000003',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    'pass',
    TIMESTAMP '2025-02-12 09:00:00',
    'All 100 PROTECTED records confirmed encrypted (AES-256-GCM).',
    'Keys held in Azure Key Vault. Rotation schedule confirmed.');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000004',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000005',
    '20000000-0000-0000-0000-000000000004',
    'fail',
    TIMESTAMP '2025-02-12 14:30:00',
    '28 of 30 write operations captured. DELETE on archive endpoint not logged.',
    'DR raised: DR-CYB-0001. Deficiency in audit hook for archive endpoint.');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000005',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000005',
    'pass',
    TIMESTAMP '2025-02-13 10:00:00',
    'All 12 admin endpoints returned HTTP 403 for operator role.',
    NULL);

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000006',
    '90000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000008',
    '20000000-0000-0000-0000-000000000003',
    'fail',
    TIMESTAMP '2025-02-13 14:00:00',
    'Endpoint /api/v1/legacy/export accepts TLS 1.2 connections.',
    'DR raised: DR-CYB-0002. Legacy endpoint excluded from TLS policy rollout.');

INSERT INTO {{DB_NAME}}.{{TBL_TEST_RESULTS}}
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('a0000000-0000-0000-0000-000000000007',
    '90000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000004',
    'inconclusive',
    TIMESTAMP '2025-04-08 08:00:00',
    '24 hours elapsed - uptime 99.9%. Full 72-hour window in progress.',
    'Monitoring dashboard live. Splunk alerts configured.');


-- =============================================================================
-- defect_reports
-- =============================================================================
INSERT INTO {{DB_NAME}}.{{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000003',
    'DR-CYB-0001',
    'Audit Log - DELETE on /api/v2/archive/ Not Captured',
    'The DELETE method on the archive endpoint does not trigger an audit log entry. Affects SYS-FUNC-001 compliance.',
    'major', 'in_progress',
    TIMESTAMP '2025-02-12 15:00:00');

INSERT INTO {{DB_NAME}}.{{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000000-0000-0000-0000-000000000002',
    'a0000000-0000-0000-0000-000000000006',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000003',
    'DR-CYB-0002',
    'TLS 1.2 Accepted on Legacy Export Endpoint',
    'The /api/v1/legacy/export endpoint was excluded from the TLS 1.3 policy rollout. Affects SYS-SEC-002 coverage.',
    'major', 'open',
    TIMESTAMP '2025-02-13 14:45:00');

INSERT INTO {{DB_NAME}}.{{TBL_DEFECT_REPORTS}}
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('b0000000-0000-0000-0000-000000000003',
    NULL,
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000002',
    'DR-CYB-0003',
    'Session Timeout Not Enforced After 15-Minute Inactivity',
    'Idle sessions remain active indefinitely. ISM S6.2.4 requires automatic session termination after 15 minutes.',
    'minor', 'open',
    TIMESTAMP '2025-03-04 11:20:00');


-- =============================================================================
-- evidence_artifacts — intentionally left empty (no evidence uploaded yet)
-- =============================================================================

-- =============================================================================
-- COLLECT STATISTICS after seed data load for accurate query plans
-- =============================================================================
COLLECT STATISTICS COLUMN (org_id)
   ON {{DB_NAME}}.{{TBL_ORGANISATIONS}};

COLLECT STATISTICS COLUMN (org_id), COLUMN (clearance)
   ON {{DB_NAME}}.{{TBL_PERSONNEL}};

COLLECT STATISTICS COLUMN (status), COLUMN (classification)
   ON {{DB_NAME}}.{{TBL_TEST_PROGRAMS}};

COLLECT STATISTICS COLUMN (verdict)
   ON {{DB_NAME}}.{{TBL_TEST_RESULTS}};

COLLECT STATISTICS COLUMN (severity), COLUMN (status)
   ON {{DB_NAME}}.{{TBL_DEFECT_REPORTS}};
