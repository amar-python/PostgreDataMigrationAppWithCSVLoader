-- =============================================================================
-- schema/sqlite/te_core_schema.sql — SQLite 3 T&E Schema
-- Placeholders replaced by adapter_sqlite.sh at deploy time.
-- SQLite differences: no native UUID, uses TEXT for all string types,
-- no ALTER TABLE ADD CONSTRAINT after creation, no schemas.
-- =============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── organisations ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_ORGANISATIONS}} (
  org_id      TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' ||
              lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' ||
              substr('89ab',abs(random()) % 4 + 1, 1) ||
              substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
  name        TEXT    NOT NULL UNIQUE,
  org_type    TEXT    NOT NULL CHECK (org_type IN ('government','prime','subcontractor','test_unit','academic')),
  country     TEXT    NOT NULL DEFAULT 'AU' CHECK (length(country) = 2),
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  is_active   INTEGER NOT NULL DEFAULT 1
);

-- ── personnel ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_PERSONNEL}} (
  person_id     TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id        TEXT    NOT NULL REFERENCES {{TBL_ORGANISATIONS}}(org_id) ON DELETE CASCADE,
  full_name     TEXT    NOT NULL,
  email         TEXT    NOT NULL UNIQUE,
  te_role       TEXT    NOT NULL CHECK (te_role IN (
                  'test_director','test_manager','test_engineer',
                  'te_analyst','safety_engineer','config_manager','observer')),
  clearance     TEXT    NOT NULL DEFAULT 'NV1' CHECK (clearance IN ('baseline','NV1','NV2','PV')),
  password_hash TEXT    NOT NULL,
  last_login_at TEXT    NULL,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  is_active     INTEGER NOT NULL DEFAULT 1
);

-- ── test_programs ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_TEST_PROGRAMS}} (
  program_id          TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id              TEXT    NOT NULL REFERENCES {{TBL_ORGANISATIONS}}(org_id),
  program_director_id TEXT    REFERENCES {{TBL_PERSONNEL}}(person_id),
  program_code        TEXT    NOT NULL UNIQUE,
  program_name        TEXT    NOT NULL,
  capability_area     TEXT    NULL,
  classification      TEXT    NOT NULL DEFAULT 'UNCLASSIFIED'
                        CHECK (classification IN ('UNCLASSIFIED','PROTECTED','SECRET','TOP SECRET')),
  status              TEXT    NOT NULL DEFAULT 'planning'
                        CHECK (status IN ('planning','active','suspended','completed','cancelled')),
  start_date          TEXT    NULL,
  end_date            TEXT    NULL CHECK (end_date IS NULL OR end_date >= start_date),
  created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── requirements ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_REQUIREMENTS}} (
  req_id              TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  program_id          TEXT    NOT NULL REFERENCES {{TBL_TEST_PROGRAMS}}(program_id) ON DELETE CASCADE,
  req_identifier      TEXT    NOT NULL,
  title               TEXT    NOT NULL,
  description         TEXT    NULL,
  req_type            TEXT    NOT NULL DEFAULT 'functional'
                        CHECK (req_type IN ('functional','performance','security','safety','interface','compliance')),
  priority            INTEGER NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
  verification_method TEXT    NOT NULL DEFAULT 'test'
                        CHECK (verification_method IN ('test','analysis','inspection','demonstration')),
  source_document     TEXT    NULL,
  created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (program_id, req_identifier)
);

-- ── test_cases ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_TEST_CASES}} (
  tc_id           TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  program_id      TEXT    NOT NULL REFERENCES {{TBL_TEST_PROGRAMS}}(program_id) ON DELETE CASCADE,
  author_id       TEXT    NOT NULL REFERENCES {{TBL_PERSONNEL}}(person_id),
  tc_identifier   TEXT    NOT NULL,
  title           TEXT    NOT NULL,
  objective       TEXT    NULL,
  preconditions   TEXT    NULL,
  steps           TEXT    NULL,
  expected_result TEXT    NULL,
  tc_type         TEXT    NOT NULL DEFAULT 'functional'
                    CHECK (tc_type IN ('functional','performance','security','regression','integration','acceptance')),
  status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','approved','active','deprecated')),
  created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (program_id, tc_identifier)
);

-- ── vcrm_entries ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_VCRM_ENTRIES}} (
  vcrm_id       TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  req_id        TEXT    NOT NULL REFERENCES {{TBL_REQUIREMENTS}}(req_id) ON DELETE CASCADE,
  tc_id         TEXT    NOT NULL REFERENCES {{TBL_TEST_CASES}}(tc_id)   ON DELETE CASCADE,
  coverage_type TEXT    NOT NULL DEFAULT 'full'
                  CHECK (coverage_type IN ('full','partial','conditional')),
  rationale     TEXT    NULL,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (req_id, tc_id)
);

-- ── defect_reports ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {{TBL_DEFECT_REPORTS}} (
  defect_id    TEXT    NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  program_id   TEXT    NOT NULL REFERENCES {{TBL_TEST_PROGRAMS}}(program_id),
  raised_by_id TEXT    NOT NULL REFERENCES {{TBL_PERSONNEL}}(person_id),
  defect_ref   TEXT    NOT NULL UNIQUE,
  title        TEXT    NOT NULL,
  description  TEXT    NULL,
  severity     TEXT    NOT NULL CHECK (severity IN ('critical','major','minor','observation')),
  status       TEXT    NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open','in_progress','resolved','closed','deferred','duplicate')),
  resolution   TEXT    NULL,
  raised_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  resolved_at  TEXT    NULL,
  created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Triggers (updated_at) ─────────────────────────────────────────────────────
CREATE TRIGGER IF NOT EXISTS trg_organisations_updated_at
  AFTER UPDATE ON {{TBL_ORGANISATIONS}}
  BEGIN UPDATE {{TBL_ORGANISATIONS}} SET updated_at = datetime('now') WHERE org_id = NEW.org_id; END;

CREATE TRIGGER IF NOT EXISTS trg_personnel_updated_at
  AFTER UPDATE ON {{TBL_PERSONNEL}}
  BEGIN UPDATE {{TBL_PERSONNEL}} SET updated_at = datetime('now') WHERE person_id = NEW.person_id; END;

CREATE TRIGGER IF NOT EXISTS trg_programs_updated_at
  AFTER UPDATE ON {{TBL_TEST_PROGRAMS}}
  BEGIN UPDATE {{TBL_TEST_PROGRAMS}} SET updated_at = datetime('now') WHERE program_id = NEW.program_id; END;

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_personnel_org   ON {{TBL_PERSONNEL}}     (org_id);
CREATE INDEX IF NOT EXISTS idx_programs_status ON {{TBL_TEST_PROGRAMS}} (status);
CREATE INDEX IF NOT EXISTS idx_req_program     ON {{TBL_REQUIREMENTS}}  (program_id);
CREATE INDEX IF NOT EXISTS idx_tc_program      ON {{TBL_TEST_CASES}}    (program_id);
CREATE INDEX IF NOT EXISTS idx_dr_severity     ON {{TBL_DEFECT_REPORTS}}(severity);
