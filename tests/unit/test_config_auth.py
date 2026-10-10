"""Unit tests for api/config.py and api/auth.py. No database, no network."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.config as config_module
from api.auth import require_api_key
from api.config import TE_TABLES, settings

pytestmark = pytest.mark.unit


def _reload_settings(monkeypatch, **env):
    """Evaluate api/config.py in a throwaway namespace with the given env vars.

    Settings reads os.environ at class-definition time, so a fresh evaluation is
    needed. importlib.reload() is deliberately avoided: it would replace the
    shared ``settings`` singleton that api.db / the routers already hold.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    namespace: dict = {"__name__": "config_under_test"}
    source = open(config_module.__file__, encoding="utf-8").read()
    exec(compile(source, config_module.__file__, "exec"), namespace)  # nosec B102 — trusted repo file
    return namespace["Settings"]()


class TestRequireApiKey:
    @pytest.fixture(autouse=True)
    def _restore_key(self):
        original = settings.API_KEY
        yield
        settings.API_KEY = original

    def test_no_key_configured_allows_request(self):
        """With API_KEY unset (local dev) every request is allowed."""
        settings.API_KEY = ""
        assert require_api_key("") is None

    def test_correct_key_is_accepted(self):
        """A matching X-API-Key header passes."""
        settings.API_KEY = "s3cret"
        assert require_api_key("s3cret") is None

    @pytest.mark.parametrize("sent", ["", "wrong", "s3cret ", "S3CRET"])
    def test_wrong_or_missing_key_is_401(self, sent):
        """A missing or mismatched key raises 401."""
        settings.API_KEY = "s3cret"
        with pytest.raises(HTTPException) as exc:
            require_api_key(sent)
        assert exc.value.status_code == 401


class TestSettings:
    def test_defaults(self, monkeypatch):
        """Unset env vars fall back to the documented local-dev defaults, including
        the Vite dev-server origin on port 8080 (issue #43)."""
        for key in ("PGHOST", "PGPORT", "CORS_ORIGINS", "API_ALLOW_DESTRUCTIVE", "API_MAX_ROWS",
                    "API_MAX_ROW_ERRORS", "MAX_UPLOAD_BYTES", "CSV_UPLOADS_SCHEMA"):
            monkeypatch.delenv(key, raising=False)
        s = _reload_settings(monkeypatch)
        assert s.PG_HOST == "localhost"
        assert s.PG_PORT == 5432
        assert s.UPLOADS_SCHEMA == "csv_uploads"
        assert s.MAX_ROWS == 100000
        assert s.MAX_ROW_ERRORS_REPORTED == 200
        assert s.MAX_UPLOAD_BYTES == 50 * 1024 * 1024
        assert s.CORS_ORIGINS == ["http://localhost:8080", "http://localhost:5173",
                                  "http://localhost:3000"]

    def test_destructive_operations_disabled_by_default(self, monkeypatch):
        """BUG-040: DELETE is off unless explicitly enabled."""
        monkeypatch.delenv("API_ALLOW_DESTRUCTIVE", raising=False)
        assert _reload_settings(monkeypatch).allow_destructive is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_destructive_truthy_values(self, monkeypatch, value):
        """1/true/yes (any case) enable destructive operations."""
        assert _reload_settings(monkeypatch, API_ALLOW_DESTRUCTIVE=value).allow_destructive

    @pytest.mark.parametrize("value", ["0", "false", "no", "enabled", ""])
    def test_destructive_other_values_stay_disabled(self, monkeypatch, value):
        """Anything else keeps destructive operations disabled."""
        assert not _reload_settings(monkeypatch, API_ALLOW_DESTRUCTIVE=value).allow_destructive

    def test_cors_origins_split_on_comma(self, monkeypatch):
        """CORS_ORIGINS is a comma-separated list."""
        s = _reload_settings(monkeypatch, CORS_ORIGINS="http://a.test,http://b.test")
        assert s.CORS_ORIGINS == ["http://a.test", "http://b.test"]

    def test_numeric_limits_read_from_env(self, monkeypatch):
        """Row and error caps are configurable via env vars."""
        s = _reload_settings(monkeypatch, API_MAX_ROWS="10", API_MAX_ROW_ERRORS="3",
                             API_POOL_GETCONN_TIMEOUT="1.5")
        assert (s.MAX_ROWS, s.MAX_ROW_ERRORS_REPORTED, s.POOL_GETCONN_TIMEOUT) == (10, 3, 1.5)


class TestTeTables:
    def test_dependency_order(self):
        """Parents precede children so T&E loads can respect foreign keys."""
        idx = {t: i for i, t in enumerate(TE_TABLES)}
        assert idx["organisations"] < idx["personnel"]
        assert idx["test_programs"] < idx["test_phases"]
        assert idx["requirements"] < idx["vcrm_entries"]
        assert idx["test_events"] < idx["test_results"]

    def test_names_are_safe_identifiers(self):
        """Every whitelisted table name is a plain lowercase identifier."""
        assert all(t.isidentifier() and t == t.lower() for t in TE_TABLES)
