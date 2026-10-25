"""pytest global configuration: environment-variable isolation between tests.

Mirrors the role of test-setup.ts in gstack: snapshots critical env vars
before each test and restores them after, preventing the common bug class
where one test sets CSV_FILE / PGPASSWORD / PATH and leaks that value into
an unrelated downstream test.
"""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests exercise the API directly via TestClient without an API key; bypass the
# require_api_key dependency for the whole test session rather than threading
# a header through every test's client.get/post/delete call.
from api.auth import require_api_key  # noqa: E402
from api.main import app  # noqa: E402

app.dependency_overrides[require_api_key] = lambda: None

# O-03: the rate-limit middleware is real for every TestClient request, and all
# tests share one bucket (TestClient always presents the same client identity).
# Left enabled, the write budget would start returning 429 partway through
# upload-heavy modules and fail tests for reasons unrelated to what they assert.
# Disable both budgets for the session — the same stance taken above for auth —
# and let tests that specifically exercise limiting set their own budgets.
from api.config import settings as _settings  # noqa: E402
from api.ratelimit import limiter as _limiter  # noqa: E402


_settings.RATE_LIMIT_READS_PER_MINUTE = 0
_settings.RATE_LIMIT_WRITES_PER_MINUTE = 0


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear limiter buckets so one test's request history cannot fail another."""
    _limiter.reset()
    yield
    _limiter.reset()


# Env vars tests are allowed to mutate; restored after every test.
_RESTORE_KEYS = (
    "CSV_FILE",
    "VALID_CSV",
    "SKIP_FILE",
    "TABLE_NAME",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PATH",
)


@pytest.fixture(autouse=True)
def _restore_env():
    baseline = {k: os.environ.get(k) for k in _RESTORE_KEYS}
    yield
    for k, v in baseline.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
