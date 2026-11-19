"""#279: the hand-written gap registers in docs/ must not contradict docs/VCRM.md.

VCRM.md is the source of truth for the status of each business requirement (BR-xx). Two checks keep the rest honest:

  1. VCRM.md agrees with its own latest headline (how many are verified, deferred, partial or not started).
  2. docs/VCRM_GAPS.md, which lists "the business requirements that are not fully verified", either lists exactly
     the requirements VCRM.md says are not verified, or says on its first lines that it is superseded.

Both read the Markdown as text; no database or network.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
VCRM = ROOT / "docs" / "VCRM.md"
VCRM_GAPS = ROOT / "docs" / "VCRM_GAPS.md"

_SYMBOLS = re.compile(r"^(✅|⚠️?|⏸️?|❌)")


def statuses() -> dict[str, str]:
    """BR-xx -> verified | partial | deferred | not started, read from VCRM.md's coverage table."""
    found: dict[str, str] = {}
    for line in VCRM.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (BR-\d+) \|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # The first rows put the status after the test-coverage columns; the later (ART) rows put it second.
        symbol = cells[1] if len(cells) > 1 and _SYMBOLS.match(cells[1]) else next(
            (c for c in cells[3:] if _SYMBOLS.match(c)), "")
        text = " ".join(cells[1:])
        if symbol.startswith("✅"):
            found[m.group(1)] = "verified"
        elif symbol.startswith("⚠"):
            found[m.group(1)] = "partial"
        elif symbol.startswith("⏸") or (symbol.startswith("❌") and "Deferred" in text):
            found[m.group(1)] = "deferred"
        elif symbol.startswith("❌"):
            found[m.group(1)] = "not started"
        else:
            found[m.group(1)] = "unread"
    return found


def latest_headline() -> tuple[int, int, int, int]:
    """(total, verified, deferred, open) from the newest '**Headline (date):**' paragraph."""
    text = VCRM.read_text(encoding="utf-8")
    m = re.search(r"\*\*Headline \(\d{4}-\d{2}-\d{2}\):\*\*.*?\*\*(\d+) of (\d+) \(\d+ %\)\*\* are verified, "
                  r"(\d+) are deferred by decision, and the other (\d+) are partial or not started", text)
    assert m, "VCRM.md has no headline in the expected shape"
    verified, total, deferred, still_open = (int(g) for g in m.groups())
    return total, verified, deferred, still_open


def test_every_requirement_status_was_read():
    unread = [b for b, s in statuses().items() if s == "unread"]
    assert unread == [], f"VCRM.md rows whose status this test cannot read: {unread}"


def test_vcrm_agrees_with_its_own_headline():
    counts = Counter(statuses().values())
    total, verified, deferred, still_open = latest_headline()
    assert (len(statuses()), counts["verified"], counts["deferred"], counts["partial"] + counts["not started"]) == (
        total, verified, deferred, still_open), (
        f"VCRM.md's table says {dict(counts)} but its latest headline says {verified} verified, {deferred} deferred, "
        f"{still_open} open of {total}: update one of them")


def test_vcrm_gaps_lists_what_vcrm_calls_not_verified_or_says_it_is_superseded():
    text = VCRM_GAPS.read_text(encoding="utf-8")
    if "superseded" in "\n".join(text.splitlines()[:12]).lower():
        return  # a banner at the top, naming what replaces it
    listed = set(re.findall(r"BR-\d+", text))
    not_verified = {b for b, s in statuses().items() if s != "verified"}
    assert listed == not_verified, (
        "docs/VCRM_GAPS.md says it lists the requirements that are not fully verified, but VCRM.md disagrees. "
        f"Only in VCRM_GAPS.md (now verified): {sorted(listed - not_verified)}. "
        f"Only in VCRM.md (not verified, missing from VCRM_GAPS.md): {sorted(not_verified - listed)}.")
