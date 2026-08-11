"""Configuration — reads libpq-style env vars, defaults to local PG 18 dev setup."""

import os


class Settings:
    PG_HOST: str = os.environ.get("PGHOST", "localhost")
    PG_PORT: int = int(os.environ.get("PGPORT", "5432"))
    PG_USER: str = os.environ.get("PGUSER", "postgres")
    PG_PASSWORD: str = os.environ.get("PGPASSWORD", "")
    PG_DATABASE: str = os.environ.get("PGDATABASE", "te_mgmt_dev")

    # Schema where dynamically created per-CSV tables + the registry live.
    UPLOADS_SCHEMA: str = os.environ.get("CSV_UPLOADS_SCHEMA", "csv_uploads")

    # Schema holding the fixed T&E tables (deploy_all.sh dev creates te_dev).
    TE_SCHEMA: str = os.environ.get("TE_SCHEMA", "te_dev")

    # CORS origins for the frontend dev server.
    CORS_ORIGINS: list = os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")

    MAX_UPLOAD_BYTES: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

    # BUG-027: cap total rows accepted per upload so a pathological file (millions
    # of rows all failing type-cast) can't monopolise the API. Default 100k rows.
    # Also enforced by te_loader.py (BUG-028) once folded into T&E mode.
    MAX_ROWS: int = int(os.environ.get("API_MAX_ROWS", "100000"))

    # BUG-027: cap the per-row error list in the response body. Prevents 100MB
    # JSON responses when a whole file fails validation. The summary counts
    # still reflect the true failed-row count.
    MAX_ROW_ERRORS_REPORTED: int = int(os.environ.get("API_MAX_ROW_ERRORS", "200"))

    # BUG-030: bound how long a request handler waits to borrow a pool slot.
    # If every one of maxconn connections is checked out (leak or long-running
    # query), the (maxconn+1)-th request raises after this many seconds instead
    # of blocking forever. The pool-exhausted handler in api/main.py returns 503.
    POOL_GETCONN_TIMEOUT: float = float(
        os.environ.get("API_POOL_GETCONN_TIMEOUT", "5.0")
    )

    # Gate for the DELETE /api/csv/files/{id} endpoint.
    # BUG-040: default is now `false` (safer). Local devs opt in via
    #   $env:API_ALLOW_DESTRUCTIVE = "true"
    # before running scripts/start-api.ps1; shared/prod deployments must set
    # it explicitly, so a forgotten env var never leaves DELETE enabled.
    allow_destructive: bool = os.environ.get("API_ALLOW_DESTRUCTIVE", "false").lower() in (
        "1", "true", "yes"
    )

    # Shared secret required on every request via the X-API-Key header.
    # Empty in local dev by default; set API_KEY before deploying anywhere reachable
    # beyond localhost.
    API_KEY: str = os.environ.get("API_KEY", "")


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

