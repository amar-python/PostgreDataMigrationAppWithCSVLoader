"""Configuration — reads libpq-style env vars, defaults to local PG 18 dev setup.

#331: the settings are a typed, validated model, built once, when the API starts (this module's import). A value
that is not of the right type or outside its range stops start-up with :class:`ConfigError`, whose message names
every bad variable, what it holds and what was expected, all at once. The two passwords are ``SecretStr``: their
value is never printed, not in that message nor in a repr; read them with ``.get_secret_value()``.

Tests build their own configuration with ``Settings.from_env({...})`` instead of patching the shared one.
``docs/ENV_VARIABLES.md`` documents every variable here, with the same default; tests/unit/test_config.py fails if
the two drift apart.

Two checks stay at start-up in api/main.py, because they say more than a type or a range can:
``policy.check_config`` (DATA_CLASSIFICATION and AUDIT_RETENTION_YEARS) and ``assert_auth_configured``
(API_ALLOW_ANONYMOUS outside API_ENV=dev).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

# M7 (#111): the classifications a deployment can honour. PROTECTED needs IRAP-assessed hosting (#49).
CLASSIFICATIONS = ("UNOFFICIAL", "OFFICIAL", "OFFICIAL: Sensitive")

# The deployments API_ENV may name: build/environments/env_<env>.sql and scripts/dev-env.ps1 use the same four.
API_ENVS = ("dev", "test", "staging", "prod")

# On/off variables. Anything else is refused: before #331 an unrecognised value such as "on" silently meant off.
_TRUE = ("1", "true", "yes")
_FALSE = ("", "0", "false", "no")


class ConfigError(ValueError):
    """The environment holds a value the API cannot run with. The message names each bad variable."""


def _flag(raw: object, *, strip: bool) -> object:
    if not isinstance(raw, str):
        return raw
    value = (raw.strip() if strip else raw).lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"expected one of {', '.join(_TRUE)} (on) or {', '.join(repr(v) for v in _FALSE)} (off)")


def _env(name: str, **constraints: Any) -> Any:
    """A field read from environment variable ``name``. Attribute names stay as they were, so callers do not change."""
    return Field(validation_alias=AliasChoices(name), **constraints)


class Settings(BaseModel):
    # Not frozen: the tests, and api/tenancy.py while it migrates a tenant's schema, assign attributes.
    model_config = ConfigDict(extra="ignore", validate_by_name=True, hide_input_in_errors=True)

    PG_HOST: str = _env("PGHOST", default="localhost")
    PG_PORT: int = _env("PGPORT", default=5432, ge=1, le=65535)
    PG_USER: str = _env("PGUSER", default="postgres")
    PG_PASSWORD: SecretStr = _env("PGPASSWORD", default=SecretStr(""))
    PG_DATABASE: str = _env("PGDATABASE", default="te_mgmt_dev")
    # M3d (#107): the runtime role the API's request pool connects as. It may only
    # read and insert in the append-only tables. PG_USER stays the owner, used at
    # startup for migrations and grants. Unset: the pool connects as PG_USER.
    APP_DB_USER: str = _env("APP_DB_USER", default="")
    APP_DB_PASSWORD: SecretStr = _env("APP_DB_PASSWORD", default=SecretStr(""))

    # Schema where dynamically created per-CSV tables + the registry live.
    UPLOADS_SCHEMA: str = _env("CSV_UPLOADS_SCHEMA", default="csv_uploads")
    # M2 (#92): tenants, users, memberships and sessions, shared by all tenants.
    CONTROL_SCHEMA: str = _env("CONTROL_SCHEMA", default="control")
    # M7 (#111, decision 7): marked on every response (X-Data-Classification); see api/policy.py, which refuses
    # anything outside CLASSIFICATIONS at start-up with a message about PROTECTED hosting.
    DATA_CLASSIFICATION: str = _env("DATA_CLASSIFICATION", default="OFFICIAL: Sensitive")
    # Minimum years to keep audit rows. Nothing in the app deletes them; this binds any operator purge.
    # api/policy.py refuses less than 1 at start-up.
    AUDIT_RETENTION_YEARS: int = _env("AUDIT_RETENTION_YEARS", default=7)
    # Lifetime of a sign-in session, in hours.
    SESSION_TTL_HOURS: int = _env("SESSION_TTL_HOURS", default=12, ge=1)
    # #296: a session not used for this many minutes is refused (0 turns the check off); the rows of sessions that
    # ended more than this many days ago are deleted by the purge (api/services/accounts.purge_sessions).
    SESSION_IDLE_MINUTES: int = _env("SESSION_IDLE_MINUTES", default=30, ge=0)
    SESSION_PURGE_GRACE_DAYS: int = _env("SESSION_PURGE_GRACE_DAYS", default=1, ge=0)
    # #102: lock an account after this many failed sign-ins within the window,
    # for the same number of minutes.
    LOGIN_MAX_FAILURES: int = _env("LOGIN_MAX_FAILURES", default=10, ge=1)
    LOGIN_LOCKOUT_MINUTES: int = _env("LOGIN_LOCKOUT_MINUTES", default=15, ge=1)
    # #95: OIDC sign-in against an IdP the deployment controls. Off unless
    # OIDC_ISSUER is set. OIDC_JWKS_URL may be https:// or, for an enclave with
    # a published key file, file://. api/oidc.check_config checks them at start-up.
    OIDC_ISSUER: str = _env("OIDC_ISSUER", default="")
    OIDC_AUDIENCE: str = _env("OIDC_AUDIENCE", default="")
    OIDC_JWKS_URL: str = _env("OIDC_JWKS_URL", default="")
    OIDC_USERNAME_CLAIM: str = _env("OIDC_USERNAME_CLAIM", default="preferred_username")

    # Schema holding the fixed T&E tables (deploy_all.sh dev creates te_dev).
    TE_SCHEMA: str = _env("TE_SCHEMA", default="te_dev")

    # CORS origins for the frontend dev server. 8080 is the port the Vite dev
    # server (scripts/start-frontend.ps1) actually listens on; 5173/3000 are
    # kept for other local setups. Comma-separated in the environment.
    CORS_ORIGINS: list[str] = _env(
        "CORS_ORIGINS", default=["http://localhost:8080", "http://localhost:5173", "http://localhost:3000"]
    )

    MAX_UPLOAD_BYTES: int = _env("MAX_UPLOAD_BYTES", default=50 * 1024 * 1024, ge=1)

    # BUG-027: cap total rows accepted per upload so a pathological file (millions
    # of rows all failing type-cast) can't monopolise the API. Default 100k rows.
    # Also enforced by te_loader.py (BUG-028) once folded into T&E mode.
    MAX_ROWS: int = _env("API_MAX_ROWS", default=100000, ge=1)

    # BUG-027: cap the per-row error list in the response body. Prevents 100MB
    # JSON responses when a whole file fails validation. The summary counts
    # still reflect the true failed-row count.
    MAX_ROW_ERRORS_REPORTED: int = _env("API_MAX_ROW_ERRORS", default=200, ge=0)

    # BUG-030: bound how long a request handler waits to borrow a pool slot.
    # If every one of maxconn connections is checked out (leak or long-running
    # query), the (maxconn+1)-th request raises after this many seconds instead
    # of blocking forever. The pool-exhausted handler in api/main.py returns 503.
    POOL_GETCONN_TIMEOUT: float = _env("API_POOL_GETCONN_TIMEOUT", default=5.0, gt=0)

    # Gate for the DELETE /api/csv/files/{id} endpoint.
    # BUG-040: default is now `false` (safer). Local devs opt in via
    #   $env:API_ALLOW_DESTRUCTIVE = "true"
    # before running scripts/start-api.ps1; shared/prod deployments must set
    # it explicitly, so a forgotten env var never leaves DELETE enabled.
    allow_destructive: bool = _env("API_ALLOW_DESTRUCTIVE", default=False)

    # #242: refuse a dynamic-mode upload unless a person confirmed its column types (`types` sent with
    # `typesConfirmed: true`), on POST /api/csv/upload and POST /api/csv/uploads. Off by default so existing
    # callers keep working; switch it on for installs that need the guarantee. T&E mode is not affected.
    REQUIRE_TYPE_CONFIRMATION: bool = _env("API_REQUIRE_TYPE_CONFIRMATION", default=False)

    # #298 (OIT-013): the shared X-API-Key is retired. Every data endpoint needs a
    # signed-in session (Authorization: Bearer), so each request has a tenant, a
    # role and a named user in the audit log.
    #
    # Local development and the test suite may call the data endpoints without
    # signing in, but only by explicit opt-in: API_ALLOW_ANONYMOUS=1 together with
    # API_ENV=dev. Anonymous requests use the deployment's default schemas, are
    # not role-checked and audit as "anonymous". The API refuses to start if the
    # opt-in is set with any other API_ENV (see assert_auth_configured in
    # api/main.py), so a deployment can never run open by accident.
    API_ALLOW_ANONYMOUS: bool = _env("API_ALLOW_ANONYMOUS", default=False)

    # O-03: which deployment this process believes it is. Only "dev" serves the
    # interactive docs and the detailed health body, uses the bootstrap fallback,
    # and may allow anonymous access (above).
    API_ENV: str = _env("API_ENV", default="dev")

    # O-03: per-client sliding-window rate limits, requests per minute.
    # Writes are budgeted far lower than reads because an upload costs orders of
    # magnitude more server work than a SELECT. Set either to 0 to disable that
    # limit (documented escape hatch for load testing).
    RATE_LIMIT_READS_PER_MINUTE: int = _env("API_RATE_LIMIT_READS", default=120, ge=0)
    RATE_LIMIT_WRITES_PER_MINUTE: int = _env("API_RATE_LIMIT_WRITES", default=20, ge=0)

    # #307 (M0 decision 1): imports (upload, stage, import) running at once on this API process; the next is refused
    # with 503 and Retry-After. 0 turns the limit off. Keep it below the DB pool size (8), which sign-in also draws on.
    MAX_CONCURRENT_IMPORTS: int = _env("API_MAX_CONCURRENT_IMPORTS", default=4, ge=0)

    # ── Parsing that differs from pydantic's own, kept as it was before #331 ──────────────────────────────────

    @field_validator("DATA_CLASSIFICATION", mode="before")
    @classmethod
    def _strip(cls, raw: object) -> object:
        return raw.strip() if isinstance(raw, str) else raw

    @field_validator("API_ENV", mode="before")
    @classmethod
    def _api_env(cls, raw: object) -> object:
        if not isinstance(raw, str):
            return raw
        value = raw.strip().lower()
        if value not in API_ENVS:
            raise ValueError(f"expected one of {', '.join(API_ENVS)}")
        return value

    @field_validator("API_ALLOW_ANONYMOUS", mode="before")
    @classmethod
    def _flag_stripped(cls, raw: object) -> object:
        return _flag(raw, strip=True)

    # These two were never stripped: " true" meant off. It is refused now rather than read either way.
    @field_validator("allow_destructive", "REQUIRE_TYPE_CONFIRMATION", mode="before")
    @classmethod
    def _flag_exact(cls, raw: object) -> object:
        return _flag(raw, strip=False)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _comma_list(cls, raw: object) -> object:
        return raw.split(",") if isinstance(raw, str) else raw

    # ── Building ──────────────────────────────────────────────────────────────────────────────────────────────

    @classmethod
    def env_names(cls) -> dict[str, str]:
        """``{environment variable: attribute}`` for every setting."""
        names = {}
        for attr, field in cls.model_fields.items():
            alias = field.validation_alias
            assert isinstance(alias, AliasChoices)  # nosec B101 — every field is declared through _env()
            names[str(alias.choices[0])] = attr
        return names

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build and validate the settings from ``environ`` (default: the process environment).

        Raises :class:`ConfigError` listing every invalid variable. The value of a secret is never in the message.
        """
        environ = os.environ if environ is None else environ
        names = cls.env_names()
        given = {name: environ[name] for name in names if name in environ}
        try:
            return cls.model_validate(given)
        except ValidationError as exc:
            raise ConfigError(_describe(exc, given)) from None


def _secret_env_names() -> set[str]:
    return {name for name, attr in Settings.env_names().items() if Settings.model_fields[attr].annotation is SecretStr}


def _describe(exc: ValidationError, given: Mapping[str, str]) -> str:
    secrets = _secret_env_names()
    lines = []
    for error in exc.errors(include_input=False):
        name = str(error["loc"][0]) if error["loc"] else "?"
        shown = "(value hidden)" if name in secrets else repr(given.get(name, ""))
        reason = error["msg"].removeprefix("Value error, ")
        lines.append(f"  {name}={shown}: {reason}")
    count = len(lines)
    head = f"Invalid configuration: {count} environment variable{'s' if count != 1 else ''} cannot be used."
    return "\n".join([head, *lines, "Fix the value(s) above (see docs/ENV_VARIABLES.md) and start the API again."])


settings = Settings.from_env()

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
