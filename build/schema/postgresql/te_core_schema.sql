-- =============================================================================
-- DEFENCE T&E MANAGEMENT — CORE SCHEMA (te_core_schema.sql)
-- =============================================================================
-- Do NOT run this file directly.
-- Run one of the environment launchers instead:
--
--   psql -U postgres -f environments/env_dev.sql
--   psql -U postgres -f environments/env_test.sql
--   psql -U postgres -f environments/env_staging.sql
--   psql -U postgres -f environments/env_prod.sql
--
-- All names (DB, schema, users, tables) are injected via \set variables
-- defined at the top of each environment file — edit ONLY those files.
-- =============================================================================

\echo ''
\echo '============================================================'
\echo ' DEFENCE T&E DATABASE SETUP'
\echo '   Environment  :' :env_label
\echo '   Database     :' :db_name
\echo '   Schema       :' :schema_name
\echo '   App User     :' :app_user
\echo '   Seed Data    :' :include_seed_data
\echo '============================================================'
\echo ''


-- =============================================================================
-- PHASE 1: DATABASE & USER
-- =============================================================================

-- Store psql variables as session parameters so DO blocks can access them.
-- (psql does not substitute :varname inside $$ dollar-quoted strings.)
SELECT
   set_config('te.env_label',    :'env_label',    false),
   set_config('te.db_name',      :'db_name',      false),
   set_config('te.app_user',     :'app_user',     false),
   set_config('te.app_password', :'app_password', false),
   set_config('te.conn_limit',   :'conn_limit',   false);

\echo '>> [1/6] Creating database:' :db_name
-- Database creation is handled by deploy_all.sh before this script runs.

\echo '>> [2/6] Creating application user:' :app_user

DO
$$
DECLARE
   v_app_user     TEXT := current_setting('te.app_user');
   v_app_password TEXT := current_setting('te.app_password');
   v_conn_limit   INT  := current_setting('te.conn_limit')::INT;
   v_env          TEXT := current_setting('te.env_label');
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = v_app_user) THEN
      EXECUTE format(
         'CREATE ROLE %I WITH LOGIN PASSWORD %L
          NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT %s',
         v_app_user, v_app_password, v_conn_limit
      );
      RAISE NOTICE '[%] Role "%" created.', v_env, v_app_user;
   ELSE
      EXECUTE format('ALTER ROLE %I PASSWORD %L CONNECTION LIMIT %s',
                     v_app_user, v_app_password, v_conn_limit);
      RAISE NOTICE '[%] Role "%" already exists — password and conn_limit refreshed.', v_env, v_app_user;
   END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE :"db_name" TO :"app_user";


-- =============================================================================
-- PHASE 2: CONNECT & SCHEMA
-- =============================================================================

\c :"db_name"

-- Re-establish session parameters after \c opens a new connection.
SELECT
   set_config('te.env_label',           :'env_label',           false),
   set_config('te.schema_name',         :'schema_name',         false),
   set_config('te.app_user',            :'app_user',            false),
   set_config('te.tbl_organisations',   :'tbl_organisations',   false),
   set_config('te.tbl_personnel',       :'tbl_personnel',       false),
   set_config('te.tbl_test_programs',   :'tbl_test_programs',   false),
   set_config('te.tbl_temp_documents',  :'tbl_temp_documents',  false),
   set_config('te.tbl_test_phases',     :'tbl_test_phases',     false),
   set_config('te.tbl_requirements',    :'tbl_requirements',    false),
   set_config('te.tbl_test_cases',      :'tbl_test_cases',      false),
   set_config('te.tbl_vcrm_entries',    :'tbl_vcrm_entries',    false),
   set_config('te.tbl_test_events',     :'tbl_test_events',     false),
   set_config('te.tbl_test_results',    :'tbl_test_results',    false),
   set_config('te.tbl_defect_reports',  :'tbl_defect_reports',  false),
   set_config('te.tbl_evidence_artifacts', :'tbl_evidence_artifacts', false);

\echo '>> [3/6] Setting up schema:' :schema_name

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "dblink";

CREATE SCHEMA IF NOT EXISTS :"schema_name";
SELECT set_config('search_path', :'schema_name' || ',public', false);

GRANT USAGE ON SCHEMA :"schema_name" TO :"app_user";
GRANT ALL ON ALL TABLES IN SCHEMA :"schema_name" TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA :"schema_name" GRANT ALL ON TABLES TO :"app_user";


-- =============================================================================
-- PHASE 3: TABLES
-- =============================================================================

\echo '>> [4/6] Creating tables'

-- ----------------------------------------------------------------------------
-- 3.1  organisations  — Defence agencies, prime contractors, test units
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_organisations" (
   org_id       UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   name         VARCHAR(200) NOT NULL UNIQUE,
   org_type     VARCHAR(50)  NOT NULL
                   CHECK (org_type IN ('government','prime','subcontractor','test_unit','academic')),
   country      CHAR(2)      NOT NULL DEFAULT 'AU',
   created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   is_active    BOOLEAN      NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE :"schema_name".:"tbl_organisations"
   IS 'Defence agencies, prime contractors, and test organisations.';

-- ----------------------------------------------------------------------------
-- 3.2  personnel  — T&E staff members and their roles
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_personnel" (
   person_id    UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   org_id       UUID         NOT NULL
                   REFERENCES :"schema_name".:"tbl_organisations"(org_id) ON DELETE CASCADE,
   full_name    VARCHAR(200) NOT NULL,
   email        VARCHAR(320) NOT NULL UNIQUE,
   te_role      VARCHAR(60)  NOT NULL
                   CHECK (te_role IN (
                      'test_director','test_manager','test_engineer',
                      'te_analyst','safety_engineer','config_manager','observer'
                   )),
   clearance    VARCHAR(20)  NOT NULL DEFAULT 'NV1'
                   CHECK (clearance IN ('baseline','NV1','NV2','PV')),
   password_hash TEXT        NOT NULL,
   last_login_at TIMESTAMPTZ,
   created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   is_active    BOOLEAN      NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE  :"schema_name".:"tbl_personnel" IS 'T&E workforce — engineers, analysts, and managers.';
COMMENT ON COLUMN :"schema_name".:"tbl_personnel".clearance IS 'Australian security clearance level.';

-- ----------------------------------------------------------------------------
-- 3.3  test_programs  — Capability acquisition / T&E programmes
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_test_programs" (
   program_id      UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   org_id          UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_organisations"(org_id),
   program_director_id UUID     REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   program_code    VARCHAR(50)  NOT NULL UNIQUE,
   program_name    VARCHAR(300) NOT NULL,
   capability_area VARCHAR(100),
   classification  VARCHAR(30)  NOT NULL DEFAULT 'UNCLASSIFIED'
                      CHECK (classification IN ('UNCLASSIFIED','PROTECTED','SECRET','TOP SECRET')),
   status          VARCHAR(30)  NOT NULL DEFAULT 'planning'
                      CHECK (status IN ('planning','active','suspended','completed','cancelled')),
   start_date      DATE,
   end_date        DATE,
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   CONSTRAINT chk_program_dates CHECK (end_date IS NULL OR end_date >= start_date)
);
COMMENT ON TABLE :"schema_name".:"tbl_test_programs"
   IS 'Top-level Defence T&E programs (e.g. LAND 400, COSPO CYB9131).';

-- ----------------------------------------------------------------------------
-- 3.4  temp_documents  — Test & Evaluation Master Plans (TEMP)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_temp_documents" (
   temp_id        UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   program_id     UUID         NOT NULL
                     REFERENCES :"schema_name".:"tbl_test_programs"(program_id) ON DELETE CASCADE,
   author_id      UUID         NOT NULL REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   version        VARCHAR(20)  NOT NULL,
   title          VARCHAR(300) NOT NULL,
   status         VARCHAR(30)  NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','in_review','approved','superseded','cancelled')),
   approved_by_id UUID         REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   approved_at    TIMESTAMPTZ,
   doc_path       TEXT,                           -- path/URL to document store
   created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   UNIQUE (program_id, version)
);
COMMENT ON TABLE :"schema_name".:"tbl_temp_documents"
   IS 'Versioned TEMP documents — governs scope, resources, and schedule.';

-- ----------------------------------------------------------------------------
-- 3.5  test_phases  — DT&E / AT&E / OT&E phases within a program
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_test_phases" (
   phase_id      UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   program_id    UUID         NOT NULL
                    REFERENCES :"schema_name".:"tbl_test_programs"(program_id) ON DELETE CASCADE,
   phase_manager_id UUID      REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   phase_code    VARCHAR(20)  NOT NULL,
   phase_type    VARCHAR(20)  NOT NULL
                    CHECK (phase_type IN ('DT&E','AT&E','OT&E','IOT&E','LFT&E','FOLLOW_ON')),
   phase_name    VARCHAR(200) NOT NULL,
   status        VARCHAR(30)  NOT NULL DEFAULT 'planned'
                    CHECK (status IN ('planned','active','completed','deferred','cancelled')),
   planned_start DATE,
   planned_end   DATE,
   actual_start  DATE,
   actual_end    DATE,
   created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   UNIQUE (program_id, phase_code)
);
COMMENT ON TABLE :"schema_name".:"tbl_test_phases"
   IS 'DT&E, AT&E, OT&E and other test phases within a program.';

-- ----------------------------------------------------------------------------
-- 3.6  requirements  — System requirements to be verified
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_requirements" (
   req_id          UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   program_id      UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_programs"(program_id) ON DELETE CASCADE,
   req_identifier  VARCHAR(50)  NOT NULL,            -- e.g. SYS-FUNC-0042
   title           VARCHAR(300) NOT NULL,
   description     TEXT,
   req_type        VARCHAR(30)  NOT NULL DEFAULT 'functional'
                      CHECK (req_type IN ('functional','performance','security',
                                          'safety','interface','compliance')),
   priority        SMALLINT     NOT NULL DEFAULT 2
                      CHECK (priority BETWEEN 1 AND 3),  -- 1=Mandatory 2=Important 3=Nice-to-have
   source_document VARCHAR(200),                          -- e.g. SRD v2.1 Section 4.3
   verification_method VARCHAR(20) NOT NULL DEFAULT 'test'
                      CHECK (verification_method IN ('test','analysis','inspection','demonstration')),
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   UNIQUE (program_id, req_identifier)
);
COMMENT ON TABLE  :"schema_name".:"tbl_requirements" IS 'System requirements subject to T&E verification.';
COMMENT ON COLUMN :"schema_name".:"tbl_requirements".priority IS '1=Mandatory, 2=Important, 3=Desirable.';

-- ----------------------------------------------------------------------------
-- 3.7  test_cases  — Individual test cases
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_test_cases" (
   tc_id           UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   phase_id        UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_phases"(phase_id) ON DELETE CASCADE,
   author_id       UUID         NOT NULL REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   tc_identifier   VARCHAR(50)  NOT NULL,            -- e.g. TC-OT-0014
   title           VARCHAR(300) NOT NULL,
   objective       TEXT,
   preconditions   TEXT,
   steps           TEXT,
   expected_result TEXT,
   tc_type         VARCHAR(30)  NOT NULL DEFAULT 'functional'
                      CHECK (tc_type IN ('functional','performance','security',
                                         'regression','integration','acceptance')),
   status          VARCHAR(30)  NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','approved','active','deprecated')),
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   UNIQUE (phase_id, tc_identifier)
);
COMMENT ON TABLE :"schema_name".:"tbl_test_cases"
   IS 'Individual test cases within a phase, with steps and expected outcomes.';

-- ----------------------------------------------------------------------------
-- 3.8  vcrm_entries  — Verification Cross Reference Matrix (VCRM)
--       Maps requirements ↔ test cases (many-to-many)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_vcrm_entries" (
   vcrm_id         UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
   req_id          UUID        NOT NULL
                      REFERENCES :"schema_name".:"tbl_requirements"(req_id) ON DELETE CASCADE,
   tc_id           UUID        NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_cases"(tc_id)    ON DELETE CASCADE,
   coverage_type   VARCHAR(30) NOT NULL DEFAULT 'full'
                      CHECK (coverage_type IN ('full','partial','conditional')),
   rationale       TEXT,
   added_by_id     UUID        REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   UNIQUE (req_id, tc_id)
);
COMMENT ON TABLE :"schema_name".:"tbl_vcrm_entries"
   IS 'VCRM: maps each requirement to one or more test cases (and vice versa).';

-- ----------------------------------------------------------------------------
-- 3.9  test_events  — Scheduled / completed test events (trials, labs, TTX)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_test_events" (
   event_id        UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   phase_id        UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_phases"(phase_id) ON DELETE CASCADE,
   event_lead_id   UUID         REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   event_code      VARCHAR(50)  NOT NULL UNIQUE,
   event_name      VARCHAR(300) NOT NULL,
   event_type      VARCHAR(30)  NOT NULL
                      CHECK (event_type IN ('lab','field_trial','simulation','TTX',
                                            'integration_test','acceptance_test')),
   location        VARCHAR(200),
   status          VARCHAR(30)  NOT NULL DEFAULT 'planned'
                      CHECK (status IN ('planned','in_progress','completed','cancelled','deferred')),
   planned_start   DATE,
   planned_end     DATE,
   actual_start    DATE,
   actual_end      DATE,
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE :"schema_name".:"tbl_test_events"
   IS 'Discrete test events (field trials, lab sessions, TTX) within a phase.';

-- ----------------------------------------------------------------------------
-- 3.10  test_results  — Outcome of each test case execution
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_test_results" (
   result_id       UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   event_id        UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_events"(event_id) ON DELETE CASCADE,
   tc_id           UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_cases"(tc_id),
   executed_by_id  UUID         REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   verdict         VARCHAR(20)  NOT NULL
                      CHECK (verdict IN ('pass','fail','blocked','not_run','inconclusive')),
   executed_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   actual_result   TEXT,
   notes           TEXT,
   evidence_ref    TEXT,                   -- path/link to raw evidence
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE :"schema_name".:"tbl_test_results"
   IS 'Execution results — one row per test case run in a test event.';

-- ----------------------------------------------------------------------------
-- 3.11  defect_reports  — Deficiencies raised during T&E
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_defect_reports" (
   defect_id       UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   result_id       UUID         REFERENCES :"schema_name".:"tbl_test_results"(result_id),
   program_id      UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_programs"(program_id),
   raised_by_id    UUID         NOT NULL REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   assigned_to_id  UUID         REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   defect_ref      VARCHAR(50)  NOT NULL UNIQUE,   -- e.g. DR-CYB-0023
   title           VARCHAR(300) NOT NULL,
   description     TEXT,
   severity        VARCHAR(20)  NOT NULL
                      CHECK (severity IN ('critical','major','minor','observation')),
   status          VARCHAR(30)  NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','in_progress','resolved','closed','deferred','duplicate')),
   resolution      TEXT,
   raised_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   resolved_at     TIMESTAMPTZ,
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
   updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE :"schema_name".:"tbl_defect_reports"
   IS 'Deficiency reports (DRs) raised during T&E execution.';

-- ----------------------------------------------------------------------------
-- 3.12  evidence_artifacts  — Supporting evidence linked to results
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS :"schema_name".:"tbl_evidence_artifacts" (
   artifact_id     UUID         DEFAULT uuid_generate_v4() PRIMARY KEY,
   result_id       UUID         NOT NULL
                      REFERENCES :"schema_name".:"tbl_test_results"(result_id) ON DELETE CASCADE,
   uploaded_by_id  UUID         NOT NULL REFERENCES :"schema_name".:"tbl_personnel"(person_id),
   artifact_name   VARCHAR(300) NOT NULL,
   artifact_type   VARCHAR(30)  NOT NULL
                      CHECK (artifact_type IN ('log','screenshot','video',
                                               'report','config_snapshot','other')),
   file_path       TEXT         NOT NULL,
   file_size_kb    INTEGER,
   checksum_sha256 CHAR(64),
   created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE :"schema_name".:"tbl_evidence_artifacts"
   IS 'Evidence artifacts (logs, screenshots, reports) attached to test results.';


-- =============================================================================
-- PHASE 4: INDEXES
-- =============================================================================

\echo '>> [4/6] Creating indexes'

CREATE INDEX IF NOT EXISTS idx_personnel_org
   ON :"schema_name".:"tbl_personnel"(org_id);
CREATE INDEX IF NOT EXISTS idx_personnel_email_trgm
   ON :"schema_name".:"tbl_personnel" USING gin(email gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_programs_org
   ON :"schema_name".:"tbl_test_programs"(org_id);
CREATE INDEX IF NOT EXISTS idx_programs_status
   ON :"schema_name".:"tbl_test_programs"(status);
CREATE INDEX IF NOT EXISTS idx_programs_code_trgm
   ON :"schema_name".:"tbl_test_programs" USING gin(program_code gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_phases_program
   ON :"schema_name".:"tbl_test_phases"(program_id);
CREATE INDEX IF NOT EXISTS idx_phases_status
   ON :"schema_name".:"tbl_test_phases"(status);

CREATE INDEX IF NOT EXISTS idx_requirements_program
   ON :"schema_name".:"tbl_requirements"(program_id);
CREATE INDEX IF NOT EXISTS idx_requirements_type
   ON :"schema_name".:"tbl_requirements"(req_type);

CREATE INDEX IF NOT EXISTS idx_testcases_phase
   ON :"schema_name".:"tbl_test_cases"(phase_id);
CREATE INDEX IF NOT EXISTS idx_testcases_status
   ON :"schema_name".:"tbl_test_cases"(status);

CREATE INDEX IF NOT EXISTS idx_vcrm_req
   ON :"schema_name".:"tbl_vcrm_entries"(req_id);
CREATE INDEX IF NOT EXISTS idx_vcrm_tc
   ON :"schema_name".:"tbl_vcrm_entries"(tc_id);

CREATE INDEX IF NOT EXISTS idx_events_phase
   ON :"schema_name".:"tbl_test_events"(phase_id);
CREATE INDEX IF NOT EXISTS idx_events_status
   ON :"schema_name".:"tbl_test_events"(status);

CREATE INDEX IF NOT EXISTS idx_results_event
   ON :"schema_name".:"tbl_test_results"(event_id);
CREATE INDEX IF NOT EXISTS idx_results_verdict
   ON :"schema_name".:"tbl_test_results"(verdict);

CREATE INDEX IF NOT EXISTS idx_defects_program
   ON :"schema_name".:"tbl_defect_reports"(program_id);
CREATE INDEX IF NOT EXISTS idx_defects_severity
   ON :"schema_name".:"tbl_defect_reports"(severity);
CREATE INDEX IF NOT EXISTS idx_defects_status
   ON :"schema_name".:"tbl_defect_reports"(status);


-- =============================================================================
-- PHASE 5: TRIGGERS — auto-update updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION :"schema_name".set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS
$$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$;

DO
$$
DECLARE
   tbl    TEXT;
   v_sch  TEXT := current_setting('te.schema_name');
BEGIN
   FOREACH tbl IN ARRAY ARRAY[
      current_setting('te.tbl_organisations'),
      current_setting('te.tbl_personnel'),
      current_setting('te.tbl_test_programs'),
      current_setting('te.tbl_temp_documents'),
      current_setting('te.tbl_test_cases'),
      current_setting('te.tbl_test_events'),
      current_setting('te.tbl_defect_reports')
   ]
   LOOP
      EXECUTE format(
         'DROP TRIGGER IF EXISTS trg_updated_at ON %I.%I;
          CREATE TRIGGER trg_updated_at
            BEFORE UPDATE ON %I.%I
            FOR EACH ROW EXECUTE FUNCTION %I.set_updated_at();',
         v_sch, tbl,
         v_sch, tbl,
         v_sch
      );
   END LOOP;
END;
$$;


-- =============================================================================
-- PHASE 6: CONDITIONAL SEED DATA
-- Inserted for dev and test environments; skipped for staging and prod.
-- =============================================================================

\if :include_seed_data

\echo '>> [5/6] Seeding realistic T&E data'

-- ── organisations ────────────────────────────────────────────────────────────
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

-- ── personnel ────────────────────────────────────────────────────────────────
INSERT INTO :"schema_name".:"tbl_personnel"
   (person_id, org_id, full_name, email, te_role, clearance, password_hash)
VALUES
   ('20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'Brigadier Helen Marsh',     'h.marsh@defence.gov.au',
    'test_director',  'PV',  '$2b$12$PLACEHOLDER_BRIG_MARSH'),

   ('20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'Col. Patrick O''Brien',     'p.obrien@defence.gov.au',
    'test_manager',   'NV2', '$2b$12$PLACEHOLDER_COL_OBRIEN'),

   ('20000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    'Dr. Anika Sharma',          'a.sharma@dst.defence.gov.au',
    'test_engineer',  'NV2', '$2b$12$PLACEHOLDER_DR_SHARMA'),

   ('20000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    'Marcus Tran',               'm.tran@leidos.com.au',
    'te_analyst',     'NV1', '$2b$12$PLACEHOLDER_TRAN'),

   ('20000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000003',
    'Yasmin El-Khoury',          'y.elkhoury@leidos.com.au',
    'te_analyst',     'NV1', '$2b$12$PLACEHOLDER_ELKHOURY'),

   ('20000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000005',
    'Flt Lt Sam Burgess',        's.burgess@defence.gov.au',
    'safety_engineer','NV2', '$2b$12$PLACEHOLDER_BURGESS')
ON CONFLICT (person_id) DO NOTHING;

-- ── test_programs ─────────────────────────────────────────────────────────────
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

-- ── temp_documents ────────────────────────────────────────────────────────────
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

-- ── test_phases ───────────────────────────────────────────────────────────────
INSERT INTO :"schema_name".:"tbl_test_phases"
   (phase_id, program_id, phase_manager_id, phase_code, phase_type, phase_name,
    status, planned_start, planned_end, actual_start)
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

-- ── requirements ─────────────────────────────────────────────────────────────
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

-- ── test_cases ────────────────────────────────────────────────────────────────
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

-- ── vcrm_entries ──────────────────────────────────────────────────────────────
INSERT INTO :"schema_name".:"tbl_vcrm_entries"
   (req_id, tc_id, coverage_type, rationale, added_by_id)
VALUES
   -- SYS-SEC-001 (MFA) → TC-OTE-001 + 002
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

-- ── test_events ───────────────────────────────────────────────────────────────
INSERT INTO :"schema_name".:"tbl_test_events"
   (event_id, phase_id, event_lead_id, event_code, event_name,
    event_type, location, status, planned_start, planned_end, actual_start, actual_end)
VALUES
   ('80000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV01',
    'COSPO OT&E Event 1 — Security & Functional Verification',
    'lab',
    'JSTF Cyber Lab, Russell Offices, ACT',
    'completed',
    '2025-02-10', '2025-02-14', '2025-02-10', '2025-02-14'),

   ('80000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV02',
    'COSPO OT&E Event 2 — Performance & Endurance',
    'lab',
    'JSTF Cyber Lab, Russell Offices, ACT',
    'in_progress',
    '2025-04-07', '2025-04-11', '2025-04-07', NULL),

   ('80000000-0000-0000-0000-000000000003',
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000002',
    'CYB9131-OTE-EV03',
    'COSPO OT&E Event 3 — ISM Compliance Inspection',
    'integration_test',
    'JSTF Cyber Lab, Russell Offices, ACT',
    'planned',
    '2025-06-16', '2025-06-20', NULL, NULL)
ON CONFLICT (event_id) DO NOTHING;

-- ── test_results ──────────────────────────────────────────────────────────────
INSERT INTO :"schema_name".:"tbl_test_results"
   (result_id, event_id, tc_id, executed_by_id,
    verdict, executed_at, actual_result, notes)
VALUES
   -- Event 1 — Security & Functional results
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

   -- Event 2 (in-progress) — one result so far
   ('90000000-0000-0000-0000-000000000007',
    '80000000-0000-0000-0000-000000000002',
    '70000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000004',
    'inconclusive', '2025-04-08 08:00:00+10',
    '24 hours elapsed — uptime 99.9%. Full 72-hour window in progress.',
    'Monitoring dashboard live. Splunk alerts configured.')
ON CONFLICT (result_id) DO NOTHING;

-- ── defect_reports ────────────────────────────────────────────────────────────
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
    'The audit hook is not wired to the archive controller. '
    'Affects SYS-FUNC-001 compliance.',
    'major', 'in_progress', '2025-02-12 15:00:00+11'),

   ('a0000000-0000-0000-0000-000000000002',
    '90000000-0000-0000-0000-000000000006',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000003',
    'DR-CYB-0002',
    'TLS 1.2 Accepted on Legacy Export Endpoint',
    'The /api/v1/legacy/export endpoint was excluded from the TLS 1.3 policy enforcement '
    'rollout. Clients using TLS 1.2 are accepted without downgrade rejection. '
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

\else

\echo '>> [5/6] Seed data SKIPPED for environment:' :env_label

\endif


-- =============================================================================
-- PHASE 6: VERIFICATION QUERIES (always run)
-- =============================================================================

\echo '>> [6/6] Verification — row counts for' :env_label

SELECT
   table_name,
   rows,
   CASE WHEN rows = 0 THEN '⚠ EMPTY' ELSE '✓ OK' END AS status
FROM (
   SELECT 'organisations'    AS table_name, COUNT(*) AS rows FROM :"schema_name".:"tbl_organisations"
   UNION ALL SELECT 'personnel',         COUNT(*) FROM :"schema_name".:"tbl_personnel"
   UNION ALL SELECT 'test_programs',     COUNT(*) FROM :"schema_name".:"tbl_test_programs"
   UNION ALL SELECT 'temp_documents',    COUNT(*) FROM :"schema_name".:"tbl_temp_documents"
   UNION ALL SELECT 'test_phases',       COUNT(*) FROM :"schema_name".:"tbl_test_phases"
   UNION ALL SELECT 'requirements',      COUNT(*) FROM :"schema_name".:"tbl_requirements"
   UNION ALL SELECT 'test_cases',        COUNT(*) FROM :"schema_name".:"tbl_test_cases"
   UNION ALL SELECT 'vcrm_entries',      COUNT(*) FROM :"schema_name".:"tbl_vcrm_entries"
   UNION ALL SELECT 'test_events',       COUNT(*) FROM :"schema_name".:"tbl_test_events"
   UNION ALL SELECT 'test_results',      COUNT(*) FROM :"schema_name".:"tbl_test_results"
   UNION ALL SELECT 'defect_reports',    COUNT(*) FROM :"schema_name".:"tbl_defect_reports"
   UNION ALL SELECT 'evidence_artifacts',COUNT(*) FROM :"schema_name".:"tbl_evidence_artifacts"
) counts
ORDER BY table_name;

-- VCRM coverage summary: requirements with and without test case coverage
SELECT
   r.req_identifier,
   r.title,
   r.req_type,
   COUNT(v.tc_id)  AS test_cases_mapped,
   CASE WHEN COUNT(v.tc_id) = 0 THEN '✗ NO COVERAGE' ELSE '✓ COVERED' END AS coverage_status
FROM       :"schema_name".:"tbl_requirements"  r
LEFT JOIN  :"schema_name".:"tbl_vcrm_entries"  v ON v.req_id = r.req_id
GROUP BY r.req_identifier, r.title, r.req_type
ORDER BY r.req_identifier;

-- Defect summary by severity and status
SELECT
   severity,
   status,
   COUNT(*) AS count
FROM :"schema_name".:"tbl_defect_reports"
GROUP BY severity, status
ORDER BY
   CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2
                 WHEN 'minor' THEN 3 ELSE 4 END,
   status;

\echo ''
\echo '============================================================'
\echo ' Setup complete for environment:' :env_label
\echo ' Database :' :db_name  '| Schema:' :schema_name
\echo '============================================================'
\echo ''
