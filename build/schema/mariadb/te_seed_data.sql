-- =============================================================================
-- schema/postgresql/te_seed_data.sql — PostgreSQL T&E Seed Data
-- =============================================================================
-- Standalone seed file extracted from te_core_schema.sql.
-- Called by adapter_postgresql.sh when SEED=true.
--
-- Uses the same psql \set variable syntax as te_core_schema.sql:
--   :"schema_name"       — schema identifier  (e.g. te_dev)
--   :"tbl_organisations" — table identifier   (e.g. organisations)
--   ... and all other tbl_* variables
--
-- All INSERTs use ON CONFLICT DO NOTHING — safe to re-run (idempotent).
-- UUIDs are fixed so repeated runs never create duplicate rows.
-- =============================================================================

\echo '>> [seed] Loading PostgreSQL T&E seed data into schema:' :schema_name

-- =============================================================================
-- organisations  (5 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_organisations"
   (org_id, name, org_type, country)
VALUES
   ('10000000-0000-0000-0000-000000000001',
    'Capability Acquisition and Sustainment Group (CASG)', 'government', 'AU'),
   ('10000000-0000-0000-0000-000000000002',
    'Defence Science and Technology (DST) Group',          'government', 'AU'),
   ('10000000-0000-0000-0000-000000000003',
    'Leidos Australia',                                    'prime',      'AU'),
   ('10000000-0000-0000-0000-000000000004',
    'BAE Systems Australia',                               'prime',      'AU'),
   ('10000000-0000-0000-0000-000000000005',
    'Joint Systems Test Facility (JSTF)',                  'test_unit',  'AU')
ON CONFLICT (org_id) DO NOTHING;

\echo '   organisations: 5 rows'


-- =============================================================================
-- personnel  (6 rows)
-- NOTE: password_hash values are bcrypt placeholders — replace before production
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_personnel"
   (person_id, org_id, full_name, email, te_role, clearance, password_hash)
VALUES
   ('20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'Brigadier Helen Marsh',  'h.marsh@defence.gov.au',
    'test_director',  'PV',  '$2b$12$PLACEHOLDER_BRIG_MARSH'),

   ('20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'Col. Patrick O''Brien',  'p.obrien@defence.gov.au',
    'test_manager',   'NV2', '$2b$12$PLACEHOLDER_COL_OBRIEN'),

   ('20000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    'Dr. Anika Sharma',       'a.sharma@dst.defence.gov.au',
    'test_engineer',  'NV2', '$2b$12$PLACEHOLDER_DR_SHARMA'),

   ('20000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    'Marcus Tran',            'm.tran@leidos.com.au',
    'te_analyst',     'NV1', '$2b$12$PLACEHOLDER_TRAN'),

   ('20000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000003',
    'Yasmin El-Khoury',       'y.elkhoury@leidos.com.au',
    'te_analyst',     'NV1', '$2b$12$PLACEHOLDER_ELKHOURY'),

   ('20000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000005',
    'Flt Lt Sam Burgess',     's.burgess@defence.gov.au',
    'safety_engineer','NV2', '$2b$12$PLACEHOLDER_BURGESS')
ON CONFLICT (person_id) DO NOTHING;

\echo '   personnel: 6 rows'


-- =============================================================================
-- test_programs  (2 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_test_programs"
   (program_id, org_id, program_director_id, program_code, program_name,
    capability_area, classification, status, start_date, end_date)
VALUES
   ('30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'CYB9131',
    'COSPO Cyber OT&E Programme',
    'Cyber / Information Warfare',
    'PROTECTED', 'active', '2024-07-01', '2026-06-30'),

   ('30000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'LAND400-P3',
    'LAND 400 Phase 3 — Infantry Fighting Vehicle T&E',
    'Land Combat Vehicle',
    'SECRET', 'active', '2024-01-15', '2027-12-31')
ON CONFLICT (program_id) DO NOTHING;

\echo '   test_programs: 2 rows'


-- =============================================================================
-- temp_documents  (3 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_temp_documents"
   (temp_id, program_id, author_id, version, title, status, doc_path)
VALUES
   ('40000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'v1.0',
    'COSPO CYB9131 Test & Evaluation Master Plan v1.0',
    'approved',
    '/documents/CYB9131/TEMP_v1.0_APPROVED.pdf'),

   ('40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'v1.1',
    'COSPO CYB9131 Test & Evaluation Master Plan v1.1 (Amendment)',
    'in_review',
    '/documents/CYB9131/TEMP_v1.1_DRAFT.pdf'),

   ('40000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'v0.5',
    'LAND 400 Phase 3 IFV T&E Master Plan v0.5',
    'draft',
    '/documents/LAND400P3/TEMP_v0.5_DRAFT.pdf')
ON CONFLICT (temp_id) DO NOTHING;

\echo '   temp_documents: 3 rows'


-- =============================================================================
-- test_phases  (3 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_test_phases"
   (phase_id, program_id, phase_manager_id, phase_code, phase_type,
    phase_name, status, planned_start, planned_end, actual_start)
VALUES
   ('50000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-DTE', 'DT&E',
    'COSPO CYB9131 — Developmental Test & Evaluation',
    'completed', '2024-07-01', '2024-12-31', '2024-07-08'),

   ('50000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE', 'OT&E',
    'COSPO CYB9131 — Operational Test & Evaluation',
    'active', '2025-01-15', '2025-12-31', '2025-01-20'),

   ('50000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'L400P3-ATE', 'AT&E',
    'LAND 400 Ph3 IFV — Acceptance Test & Evaluation',
    'planned', '2025-06-01', '2026-03-31', NULL)
ON CONFLICT (phase_id) DO NOTHING;

\echo '   test_phases: 3 rows'


-- =============================================================================
-- requirements  (8 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_requirements"
   (req_id, program_id, req_identifier, title, req_type,
    priority, source_document, verification_method)
VALUES
   ('60000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    'SYS-SEC-001', 'Multi-Factor Authentication Enforcement',
    'security', 1, 'CYB9131 SRD v2.3 §4.1', 'test'),

   ('60000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    'SYS-SEC-002', 'Data-at-Rest Encryption (AES-256)',
    'security', 1, 'CYB9131 SRD v2.3 §4.2', 'test'),

   ('60000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000001',
    'SYS-PERF-001', 'System Availability — 99.5% Uptime SLA',
    'performance', 1, 'CYB9131 SRD v2.3 §5.1', 'test'),

   ('60000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000001',
    'SYS-FUNC-001', 'Audit Log — All User Actions Captured',
    'functional', 1, 'CYB9131 SRD v2.3 §6.3', 'test'),

   ('60000000-0000-0000-0000-000000000005',
    '30000000-0000-0000-0000-000000000001',
    'SYS-FUNC-002', 'Role-Based Access Control (RBAC) Enforcement',
    'functional', 1, 'CYB9131 SRD v2.3 §6.4', 'test'),

   ('60000000-0000-0000-0000-000000000006',
    '30000000-0000-0000-0000-000000000001',
    'SYS-COMP-001', 'ISM Control Compliance — Section 3 (Gateways)',
    'compliance', 1, 'ACSC ISM 2024 §3', 'inspection'),

   ('60000000-0000-0000-0000-000000000007',
    '30000000-0000-0000-0000-000000000002',
    'IFV-PERF-001', 'Cross-Country Speed — 40 km/h Minimum',
    'performance', 1, 'LAND400 SRD v1.0 §8.2', 'test'),

   ('60000000-0000-0000-0000-000000000008',
    '30000000-0000-0000-0000-000000000002',
    'IFV-SAF-001', 'Crew Survivability — STANAG 4569 Level 4',
    'safety', 1, 'LAND400 SRD v1.0 §9.1', 'analysis')
ON CONFLICT (req_id) DO NOTHING;

\echo '   requirements: 8 rows'


-- =============================================================================
-- test_cases  (8 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_test_cases"
   (tc_id, phase_id, author_id, tc_identifier, title, tc_type,
    objective, preconditions, expected_result, status)
VALUES
   ('70000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-001',
    'MFA — Valid TOTP Login Succeeds',
    'security',
    'Verify system grants access when correct TOTP code is supplied with valid credentials.',
    'User account active; TOTP seed registered; system clock synchronised (NTP).',
    'User authenticated and session token issued within 3 seconds.',
    'approved'),

   ('70000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-002',
    'MFA — Brute-Force Lockout After 5 Failures',
    'security',
    'Verify account is locked after 5 consecutive incorrect TOTP codes.',
    'User account active; TOTP seed registered.',
    'Account locked after 5th failure; alert generated; unlock requires admin action.',
    'approved'),

   ('70000000-0000-0000-0000-000000000003',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-003',
    'Encryption — Verify AES-256 Applied to Stored Classified Data',
    'security',
    'Confirm classified records are stored encrypted using AES-256.',
    'Test dataset of 100 PROTECTED records loaded; direct DB access available.',
    'All records retrieved from DB store show AES-256 ciphertext; plaintext not recoverable without key.',
    'approved'),

   ('70000000-0000-0000-0000-000000000004',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000004',
    'TC-OTE-004',
    'Availability — Sustained Load Over 72-Hour Window',
    'performance',
    'Confirm system sustains 99.5% uptime under simulated operational load for 72 hours.',
    'Load profile: 500 concurrent users; monitoring (Splunk) active; baseline established.',
    'System uptime ≥ 99.5% over full 72-hour window; no unhandled exceptions.',
    'approved'),

   ('70000000-0000-0000-0000-000000000005',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000004',
    'TC-OTE-005',
    'Audit Log — Verify All Write Operations Are Captured',
    'functional',
    'Confirm every CREATE, UPDATE, DELETE action is recorded in the audit log.',
    'Audit logging enabled; test user with write access prepared.',
    'Audit log entries present for all 30 prescribed write operations; timestamps within ±1s.',
    'approved'),

   ('70000000-0000-0000-0000-000000000006',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'TC-OTE-006',
    'RBAC — Operator Cannot Access Admin Functions',
    'functional',
    'Verify operator role cannot invoke admin-only API endpoints.',
    'Operator account provisioned; admin endpoints documented.',
    'All admin endpoints return HTTP 403 for operator role; no privilege escalation path found.',
    'approved'),

   ('70000000-0000-0000-0000-000000000007',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000005',
    'TC-OTE-007',
    'ISM Compliance — Gateway Configuration Inspection',
    'acceptance',
    'Inspect gateway configuration against ACSC ISM Section 3 controls.',
    'Live gateway config exported; ISM checklist v2024 prepared.',
    'All 18 mandatory ISM §3 controls satisfied; zero critical gaps.',
    'approved'),

   ('70000000-0000-0000-0000-000000000008',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000005',
    'TC-OTE-008',
    'Data-in-Transit — TLS 1.3 Enforcement on All APIs',
    'security',
    'Confirm all REST API endpoints enforce TLS 1.3 minimum.',
    'Network capture tool (Wireshark) configured; test client supporting TLS 1.2 and 1.3 ready.',
    'All endpoints negotiate TLS 1.3; TLS 1.2 connections rejected with handshake failure.',
    'approved')
ON CONFLICT (tc_id) DO NOTHING;

\echo '   test_cases: 8 rows'


-- =============================================================================
-- vcrm_entries  (8 rows — 100% coverage for CYB9131)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_vcrm_entries"
   (req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   -- SYS-SEC-001 (MFA) → TC-OTE-001 + TC-OTE-002
   ('60000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    'full',    'Positive path — valid TOTP grants access.',
    '20000000-0000-0000-0000-000000000002'),

   ('60000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000002',
    'full',    'Negative path — brute-force lockout enforces MFA resilience.',
    '20000000-0000-0000-0000-000000000002'),

   -- SYS-SEC-002 (AES-256) → TC-OTE-003 + TC-OTE-008
   ('60000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000003',
    'full',    'Directly verifies AES-256 applied to stored classified data.',
    '20000000-0000-0000-0000-000000000002'),

   ('60000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000008',
    'partial', 'TLS-in-transit complements data-at-rest encryption coverage.',
    '20000000-0000-0000-0000-000000000002'),

   -- SYS-PERF-001 (Availability) → TC-OTE-004
   ('60000000-0000-0000-0000-000000000003',
    '70000000-0000-0000-0000-000000000004',
    'full',    '72-hour load test directly validates the 99.5% SLA.',
    '20000000-0000-0000-0000-000000000002'),

   -- SYS-FUNC-001 (Audit Log) → TC-OTE-005
   ('60000000-0000-0000-0000-000000000004',
    '70000000-0000-0000-0000-000000000005',
    'full',    'Covers all write operations in prescribed test scenarios.',
    '20000000-0000-0000-0000-000000000002'),

   -- SYS-FUNC-002 (RBAC) → TC-OTE-006
   ('60000000-0000-0000-0000-000000000005',
    '70000000-0000-0000-0000-000000000006',
    'full',    'Directly validates operator-role access restrictions.',
    '20000000-0000-0000-0000-000000000002'),

   -- SYS-COMP-001 (ISM Compliance) → TC-OTE-007
   ('60000000-0000-0000-0000-000000000006',
    '70000000-0000-0000-0000-000000000007',
    'full',    'Inspection-based verification of all ISM §3 gateway controls.',
    '20000000-0000-0000-0000-000000000002')
ON CONFLICT (req_id, tc_id) DO NOTHING;

\echo '   vcrm_entries: 8 rows (100% CYB9131 coverage)'


-- =============================================================================
-- test_events  (3 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_test_events"
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status, planned_start, planned_end,
    actual_start, actual_end)
VALUES
   ('80000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV01',
    'COSPO OT&E Event 1 — Security & Functional Verification',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'completed',
    '2025-02-10', '2025-02-14', '2025-02-10', '2025-02-14'),

   ('80000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV02',
    'COSPO OT&E Event 2 — Performance & Endurance',
    'lab', 'JSTF Cyber Lab, Russell Offices, ACT',
    'in_progress',
    '2025-04-07', '2025-04-11', '2025-04-07', NULL),

   ('80000000-0000-0000-0000-000000000003',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV03',
    'COSPO OT&E Event 3 — ISM Compliance Inspection',
    'integration_test', 'JSTF Cyber Lab, Russell Offices, ACT',
    'planned',
    '2025-06-16', '2025-06-20', NULL, NULL)
ON CONFLICT (event_id) DO NOTHING;

\echo '   test_events: 3 rows'


-- =============================================================================
-- test_results  (7 rows — 4 pass, 2 fail, 1 inconclusive)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_test_results"
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   ('90000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    'pass', '2025-02-11 09:35:00+11',
    'User authenticated in 1.8s; session token issued successfully.',
    'Repeated 20 times across 4 user accounts — all passed.'),

   ('90000000-0000-0000-0000-000000000002',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    'pass', '2025-02-11 11:10:00+11',
    'Account locked on 5th failed attempt; alert triggered; admin unlock required.',
    'Lockout time recorded as 47ms after final failure — within spec.'),

   ('90000000-0000-0000-0000-000000000003',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    'pass', '2025-02-12 09:00:00+11',
    'All 100 PROTECTED records confirmed encrypted (AES-256-GCM). Plaintext unrecoverable.',
    'Keys held in Azure Key Vault; rotation schedule confirmed.'),

   ('90000000-0000-0000-0000-000000000004',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000005',
    '20000000-0000-0000-0000-000000000004',
    'fail', '2025-02-12 14:30:00+11',
    '28 of 30 write operations captured. DELETE on /api/v2/archive/ endpoint not logged.',
    'DR raised: DR-CYB-0001. Deficiency in audit hook for archive endpoint.'),

   ('90000000-0000-0000-0000-000000000005',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000005',
    'pass', '2025-02-13 10:00:00+11',
    'All 12 admin endpoints returned HTTP 403 for operator role. No escalation path found.',
    NULL),

   ('90000000-0000-0000-0000-000000000006',
    '80000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000008',
    '20000000-0000-0000-0000-000000000003',
    'fail', '2025-02-13 14:00:00+11',
    'Endpoint /api/v1/legacy/export accepts TLS 1.2 connections — not rejected.',
    'DR raised: DR-CYB-0002. Legacy endpoint not in scope of TLS policy rollout.'),

   ('90000000-0000-0000-0000-000000000007',
    '80000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000004',
    'inconclusive', '2025-04-08 08:00:00+10',
    '24 hours elapsed — uptime 99.9%. Full 72-hour window in progress.',
    'Monitoring dashboard live. Splunk alerts configured.')
ON CONFLICT (result_id) DO NOTHING;

\echo '   test_results: 7 rows (4 pass, 2 fail, 1 inconclusive)'


-- =============================================================================
-- defect_reports  (3 rows)
-- =============================================================================
INSERT INTO :"schema_name".:"tbl_defect_reports"
   (defect_id, result_id, program_id, raised_by_id, assigned_to_id,
    defect_ref, title, description, severity, status, raised_at)
VALUES
   ('a0000000-0000-0000-0000-000000000001',
    '90000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000003',
    'DR-CYB-0001',
    'Audit Log — DELETE on /api/v2/archive/ Not Captured',
    'The DELETE method on the /api/v2/archive/ endpoint does not trigger an audit log entry. '
    'The audit hook is not wired to the archive controller. Affects SYS-FUNC-001 compliance.',
    'major', 'in_progress', '2025-02-12 15:00:00+11'),

   ('a0000000-0000-0000-0000-000000000002',
    '90000000-0000-0000-0000-000000000006',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000003',
    'DR-CYB-0002',
    'TLS 1.2 Accepted on Legacy Export Endpoint',
    'The /api/v1/legacy/export endpoint was excluded from the TLS 1.3 policy enforcement rollout. '
    'Clients using TLS 1.2 are accepted without downgrade rejection. '
    'Affects SYS-SEC-002 partial coverage and ISM §3 gateway controls.',
    'major', 'open', '2025-02-13 14:45:00+11'),

   ('a0000000-0000-0000-0000-000000000003',
    NULL,
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000002',
    'DR-CYB-0003',
    'Session Timeout Not Enforced After 15-Minute Inactivity',
    'Idle sessions remain active indefinitely. ISM §6.2.4 requires automatic session '
    'termination after 15 minutes of inactivity. Observed during operational walkthrough.',
    'minor', 'open', '2025-03-04 11:20:00+11')
ON CONFLICT (defect_id) DO NOTHING;

\echo '   defect_reports: 3 rows'

-- evidence_artifacts — intentionally empty (no evidence files uploaded yet)
\echo '   evidence_artifacts: 0 rows (intentionally empty)'

\echo '>> [seed] PostgreSQL seed data load complete.'
