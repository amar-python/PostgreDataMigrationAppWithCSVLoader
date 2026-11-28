"""#296: the new session settings are documented where operators look (docs/ENV_VARIABLES.md).

Without a database: a setting nobody can find is as good as none. Both are read from the environment with a default
the table must state, and the purge script an operator schedules must be named in the operator guide.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]


def env_row(name: str) -> str:
    text = (ROOT / "docs" / "ENV_VARIABLES.md").read_text(encoding="utf-8")
    match = re.search(rf"^\| `{name}` \|(.*)$", text, re.MULTILINE)
    assert match, f"docs/ENV_VARIABLES.md must document {name}"
    return match.group(1)


def test_the_idle_timeout_is_documented_with_its_default_and_how_to_turn_it_off():
    row = env_row("SESSION_IDLE_MINUTES")
    assert "30" in row and "0" in row and "idle" in row.lower(), row


def test_the_purge_grace_period_is_documented_with_its_default():
    row = env_row("SESSION_PURGE_GRACE_DAYS")
    assert "1" in row and "purge" in row.lower(), row


def test_the_operator_guide_names_the_purge_script():
    guide = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    assert re.search(r"scripts[\\/]purge_sessions\.py", guide), "the guide writes script paths either way"
