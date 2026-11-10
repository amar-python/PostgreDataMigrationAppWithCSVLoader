"""psql on Windows (client encoding WIN1252) does not skip a UTF-8 BOM and
fails the launcher with 'syntax error at or near "ï»¿"'. Linux CI skips it,
so guard the shipped SQL templates here."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "build" / "environments").glob("*.example.sql")) + [
    ROOT / "build" / "te_core_schema.sql",
    ROOT / "build" / "schema" / "postgresql" / "te_core_schema.sql",
]


@pytest.mark.unit
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_sql_has_no_utf8_bom(path):
    assert path.exists(), path
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{path.name} starts with a UTF-8 BOM"


@pytest.mark.unit
def test_all_four_env_templates_covered():
    assert len([p for p in FILES if p.name.startswith("env_")]) == 4
