"""pytest global configuration: environment-variable isolation between tests.

Mirrors the role of test-setup.ts in gstack: snapshots critical env vars
before each test and restores them after, preventing the common bug class
where one test sets CSV_FILE / PGPASSWORD / PATH and leaks that value into
an unrelated downstream test.
"""
import os
import pytest

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
