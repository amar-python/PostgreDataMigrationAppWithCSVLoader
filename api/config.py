"""Configuration — reads libpq-style env vars, defaults to local PG 18 dev setup."""

import os


class Settings:
    PG_HOST: str = os.environ.get("PGHOST", "localhost")
    PG_PORT: int = int(os.environ.get("PGPORT", "5433"))
    PG_USER: str = os.environ.get("PGUSER", "postgres")
    PG_PASSWORD: str = os.environ.get("PGPASSWORD", "")
    PG_DATABASE: str = os.environ.get("PGDATABASE", "te_mgmt_dev")

    # Schema where dynamically created per-CSV tables + the registry live.
    UPLOADS_SCHEMA: str = os.environ.get("CSV_UPLOADS_SCHEMA", "csv_uploads")

    # Schema holding the fixed T&E tables (deploy_all.sh dev creates te_dev).
    TE_SCHEMA: str = os.environ.get("TE_SCHEMA", "te_dev")

    # CORS origins for the frontend dev server.
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
        ).split(",")
        if origin.strip()
    ]

    MAX_UPLOAD_BYTES: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


settings = Settings()

# The 12 fixed T&E tables (te_core_schema.sql). Whitelist for T&E-mode loads.
TE_TABLES = [
    "organisations",
    "personnel",
    "test_programs",
    "temp_documents",
    "test_phases",
    "requirements",
    "test_cases",
    "vcrm_entries",
    "test_events",
    "test_results",
    "defect_reports",
    "evidence_artifacts",
]
