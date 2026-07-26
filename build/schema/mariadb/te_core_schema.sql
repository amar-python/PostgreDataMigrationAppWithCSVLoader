-- =============================================================================
-- schema/mariadb/te_core_schema.sql — MariaDB / MySQL T&E Schema
-- Placeholders are replaced by adapter_mariadb.sh at deploy time.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `{{DB_NAME}}`
  CHARACTER SET {{CHARSET}}
  COLLATE {{COLLATION}};

USE `{{DB_NAME}}`;

-- Create app user (idempotent)
CREATE USER IF NOT EXISTS '{{APP_USER}}'@'%' IDENTIFIED BY '{{APP_PASSWORD}}';
GRANT ALL PRIVILEGES ON `{{DB_NAME}}`.* TO '{{APP_USER}}'@'%';
FLUSH PRIVILEGES;

-- ── organisations ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_ORGANISATIONS}}` (
  org_id       CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  name         VARCHAR(200) NOT NULL UNIQUE,
  org_type     ENUM('government','prime','subcontractor','test_unit','academic') NOT NULL,
  country      CHAR(2)      NOT NULL DEFAULT 'AU',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_active    TINYINT(1)   NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── personnel ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_PERSONNEL}}` (
  person_id     CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  org_id        CHAR(36)     NOT NULL,
  full_name     VARCHAR(200) NOT NULL,
  email         VARCHAR(320) NOT NULL UNIQUE,
  te_role       ENUM('test_director','test_manager','test_engineer',
                     'te_analyst','safety_engineer','config_manager','observer') NOT NULL,
  clearance     ENUM('baseline','NV1','NV2','PV') NOT NULL DEFAULT 'NV1',
  password_hash TEXT         NOT NULL,
  last_login_at DATETIME     NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_active     TINYINT(1)   NOT NULL DEFAULT 1,
  CONSTRAINT fk_personnel_org FOREIGN KEY (org_id)
    REFERENCES `{{TBL_ORGANISATIONS}}` (org_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── test_programs ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_TEST_PROGRAMS}}` (
  program_id          CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  org_id              CHAR(36)     NOT NULL,
  program_director_id CHAR(36)     NULL,
  program_code        VARCHAR(50)  NOT NULL UNIQUE,
  program_name        VARCHAR(300) NOT NULL,
  capability_area     VARCHAR(100) NULL,
  classification      ENUM('UNCLASSIFIED','PROTECTED','SECRET','TOP SECRET') NOT NULL DEFAULT 'UNCLASSIFIED',
  status              ENUM('planning','active','suspended','completed','cancelled') NOT NULL DEFAULT 'planning',
  start_date          DATE         NULL,
  end_date            DATE         NULL,
  created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_programs_org  FOREIGN KEY (org_id) REFERENCES `{{TBL_ORGANISATIONS}}` (org_id),
  CONSTRAINT fk_programs_dir  FOREIGN KEY (program_director_id) REFERENCES `{{TBL_PERSONNEL}}` (person_id),
  CONSTRAINT chk_program_dates CHECK (end_date IS NULL OR end_date >= start_date)
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── requirements ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_REQUIREMENTS}}` (
  req_id              CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  program_id          CHAR(36)     NOT NULL,
  req_identifier      VARCHAR(50)  NOT NULL,
  title               VARCHAR(300) NOT NULL,
  description         TEXT         NULL,
  req_type            ENUM('functional','performance','security','safety','interface','compliance') NOT NULL DEFAULT 'functional',
  priority            TINYINT      NOT NULL DEFAULT 2,
  verification_method ENUM('test','analysis','inspection','demonstration') NOT NULL DEFAULT 'test',
  source_document     VARCHAR(200) NULL,
  created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_req_program (program_id, req_identifier),
  CONSTRAINT fk_req_program FOREIGN KEY (program_id) REFERENCES `{{TBL_TEST_PROGRAMS}}` (program_id) ON DELETE CASCADE,
  CONSTRAINT chk_req_priority CHECK (priority BETWEEN 1 AND 3)
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── test_cases ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_TEST_CASES}}` (
  tc_id           CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  program_id      CHAR(36)     NOT NULL,
  author_id       CHAR(36)     NOT NULL,
  tc_identifier   VARCHAR(50)  NOT NULL,
  title           VARCHAR(300) NOT NULL,
  objective       TEXT         NULL,
  preconditions   TEXT         NULL,
  steps           TEXT         NULL,
  expected_result TEXT         NULL,
  tc_type         ENUM('functional','performance','security','regression','integration','acceptance') NOT NULL DEFAULT 'functional',
  status          ENUM('draft','approved','active','deprecated') NOT NULL DEFAULT 'draft',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_tc_program (program_id, tc_identifier),
  CONSTRAINT fk_tc_program FOREIGN KEY (program_id) REFERENCES `{{TBL_TEST_PROGRAMS}}` (program_id) ON DELETE CASCADE,
  CONSTRAINT fk_tc_author  FOREIGN KEY (author_id)  REFERENCES `{{TBL_PERSONNEL}}` (person_id)
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── vcrm_entries ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_VCRM_ENTRIES}}` (
  vcrm_id       CHAR(36)    NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  req_id        CHAR(36)    NOT NULL,
  tc_id         CHAR(36)    NOT NULL,
  coverage_type ENUM('full','partial','conditional') NOT NULL DEFAULT 'full',
  rationale     TEXT        NULL,
  created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_vcrm (req_id, tc_id),
  CONSTRAINT fk_vcrm_req FOREIGN KEY (req_id) REFERENCES `{{TBL_REQUIREMENTS}}` (req_id) ON DELETE CASCADE,
  CONSTRAINT fk_vcrm_tc  FOREIGN KEY (tc_id)  REFERENCES `{{TBL_TEST_CASES}}` (tc_id)   ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── defect_reports ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{{TBL_DEFECT_REPORTS}}` (
  defect_id      CHAR(36)     NOT NULL DEFAULT (UUID()) PRIMARY KEY,
  program_id     CHAR(36)     NOT NULL,
  raised_by_id   CHAR(36)     NOT NULL,
  defect_ref     VARCHAR(50)  NOT NULL UNIQUE,
  title          VARCHAR(300) NOT NULL,
  description    TEXT         NULL,
  severity       ENUM('critical','major','minor','observation') NOT NULL,
  status         ENUM('open','in_progress','resolved','closed','deferred','duplicate') NOT NULL DEFAULT 'open',
  resolution     TEXT         NULL,
  raised_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at    DATETIME     NULL,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_dr_program FOREIGN KEY (program_id)   REFERENCES `{{TBL_TEST_PROGRAMS}}` (program_id),
  CONSTRAINT fk_dr_raiser  FOREIGN KEY (raised_by_id) REFERENCES `{{TBL_PERSONNEL}}` (person_id)
) ENGINE=InnoDB DEFAULT CHARSET={{CHARSET}} COLLATE={{COLLATION}};

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_personnel_org   ON `{{TBL_PERSONNEL}}`     (org_id);
CREATE INDEX IF NOT EXISTS idx_programs_status ON `{{TBL_TEST_PROGRAMS}}` (status);
CREATE INDEX IF NOT EXISTS idx_req_program     ON `{{TBL_REQUIREMENTS}}`  (program_id);
CREATE INDEX IF NOT EXISTS idx_tc_program      ON `{{TBL_TEST_CASES}}`    (program_id);
CREATE INDEX IF NOT EXISTS idx_dr_severity     ON `{{TBL_DEFECT_REPORTS}}`(severity);
CREATE INDEX IF NOT EXISTS idx_dr_status       ON `{{TBL_DEFECT_REPORTS}}`(status);
