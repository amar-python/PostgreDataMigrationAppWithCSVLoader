"""#322 (SE-01): the security findings bandit had never been shown, because it scanned 19 of 74 source files.

Widening bandit to every source file surfaced 12 findings. Three were fixed in code, and these tests pin them:

  * container/smoke_test.py and scripts/sample_verification_run.py handed any URL to urllib, which also follows
    file: URLs. Both now refuse anything but http(s) before making the request.
  * alembic/versions/0006_append_only_audit.py put the schema name into an SQL string literal without escaping its
    single quotes. The name is operator configuration, not user input, but a quote in it broke the statement.

The other nine are annotated in place with the reason: six SQL strings in the verification script built from names
in this deployment's own API response (not rewritten, because they could not be run where the change was made),
one JUnit XML parse of a file the script itself had pytest write, and the two string-built DO blocks in the
migration, whose identifiers are quoted by the dialect.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts import sample_verification_run as verification

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]


def load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.test/x", "gopher://example.test", "/etc/passwd"])
def test_the_smoke_test_refuses_a_url_that_is_not_http(url):
    smoke = load("container/smoke_test.py")
    with pytest.raises(ValueError, match="http"):
        smoke.call(url)


@pytest.mark.parametrize("base", ["file:///etc", "ftp://example.test", "localhost:8000", ""])
def test_the_verification_script_refuses_an_api_address_that_is_not_http(base):
    with pytest.raises(ValueError, match="http"):
        verification.Api(base)


@pytest.mark.parametrize("base", ["http://localhost:8000", "https://api.example.test/", "HTTP://LOCALHOST:8000"])
def test_the_verification_script_accepts_http_and_https(base):
    assert verification.Api(base).base.startswith(("http", "HTTP"))


@pytest.mark.parametrize("value", ["csv_uploads", "o'brien", "'; DROP TABLE audit_log; --", "''", ""])
def test_the_migration_writes_a_schema_name_as_one_sql_string_literal(value):
    literal = load("alembic/versions/0006_append_only_audit.py")._literal(value)
    assert literal.startswith("'") and literal.endswith("'") and len(literal) >= 2
    inner = literal[1:-1]
    assert inner.replace("''", "").count("'") == 0, f"an unescaped quote would end the literal early: {literal}"
    assert inner.replace("''", "'") == value, "escaping must be reversible: the database must see the original name"


def test_an_ordinary_schema_name_is_unchanged_by_the_escaping():
    assert load("alembic/versions/0006_append_only_audit.py")._literal("csv_uploads") == "'csv_uploads'"
