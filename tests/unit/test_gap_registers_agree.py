"""#279: the hand-written gap registers in docs/ must not contradict docs/VCRM.md.

VCRM.md is the source of truth for the status of each business requirement (BR-xx). Two checks keep the rest honest:

  1. VCRM.md agrees with its own latest headline (how many are verified, deferred, partial or not started).
  2. docs/VCRM_GAPS.md, which lists "the business requirements that are not fully verified", either lists exactly
     the requirements VCRM.md says are not verified, or says on its first lines that it is superseded.

Three more cover the registers that are not a copy of VCRM.md (GAP_ANALYSIS, ENGINE_PARITY_TODO, HANDOFF-20261104):

  3. each opens with a pointer to the document that owns the status, and every file its banner names exists
     (the first draft of the GAP_ANALYSIS banner pointed at a file that was never written);
  4. a requirement status quoted in a banner, "BR-02 (Deferred ...)", is the status VCRM.md gives, and every OIT-nnn
     cited anywhere is an entry in the tracker;
  5. the per-engine table counts in ENGINE_PARITY_TODO match the DDL. Teradata was reported as 1 table for two months
     because a grep for "CREATE TABLE" matched one comment line; the file defines 12 with "CREATE SET TABLE".

All read the Markdown or the DDL as text; no database or network.
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
DOCS = ROOT / "docs"
GAP_ANALYSIS = DOCS / "GAP_ANALYSIS.md"
ENGINE_PARITY = DOCS / "ENGINE_PARITY_TODO.md"
HANDOFF = DOCS / "HANDOFF-20261104.md"
RECONCILIATION = DOCS / "AUDIT_RECONCILIATION_2026-11-20.md"
TRACKER = DOCS / "Outstanding Items Tracker_Grok.txt"
REGISTERS = [GAP_ANALYSIS, ENGINE_PARITY, HANDOFF]
BANNER_LINES = 25  # "on its first lines": the part a reader sees before deciding whether to trust the file

_SYMBOLS = re.compile(r"^(✅|⚠️?|⏸️?|❌)")


def statuses() -> dict[str, str]:
    """BR-xx -> verified | partial | deferred | not started, read from VCRM.md's sections 1 and 2.

    Only the text before "## 3." is read. Section 6 keeps the 2026-11-20 review's own table of statuses as a record;
    a later row there would otherwise override the current status in section 2.
    """
    found: dict[str, str] = {}
    text = VCRM.read_text(encoding="utf-8")
    current = text.split("\n## 3.", 1)[0]
    assert current != text, "VCRM.md has no '## 3.' heading; statuses() reads only sections 1 and 2"
    for line in current.splitlines():
        m = re.match(r"\| (BR-\d+) \|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # The first rows put the status after the test-coverage columns; the later (ART) rows put it second.
        symbol = (
            cells[1]
            if len(cells) > 1 and _SYMBOLS.match(cells[1])
            else next((c for c in cells[3:] if _SYMBOLS.match(c)), "")
        )
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
    m = re.search(
        r"\*\*Headline \(\d{4}-\d{2}-\d{2}\):\*\*.*?\*\*(\d+) of (\d+) \(\d+ %\)\*\* are verified, "
        r"(\d+) are deferred by decision, and the other (\d+) are partial or not started",
        text,
    )
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
        total,
        verified,
        deferred,
        still_open,
    ), (
        f"VCRM.md's table says {dict(counts)} but its latest headline says {verified} verified, {deferred} deferred, "
        f"{still_open} open of {total}: update one of them"
    )


def test_vcrm_gaps_lists_what_vcrm_calls_not_verified_or_says_it_is_superseded():
    text = VCRM_GAPS.read_text(encoding="utf-8")
    if "superseded" in "\n".join(text.splitlines()[:12]).lower():
        return  # a banner at the top, naming what replaces it
    listed = set(re.findall(r"BR-\d+", text))
    not_verified = {b for b, s in statuses().items() if s != "verified"}
    assert listed == not_verified, (
        "docs/VCRM_GAPS.md says it lists the requirements that are not fully verified, but VCRM.md disagrees. "
        f"Only in VCRM_GAPS.md (now verified): {sorted(listed - not_verified)}. "
        f"Only in VCRM.md (not verified, missing from VCRM_GAPS.md): {sorted(not_verified - listed)}."
    )


# --- the registers that are not a copy of VCRM.md ---------------------------------------------------------------


def banner(path: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[:BANNER_LINES])


@pytest.mark.parametrize("register", REGISTERS, ids=lambda p: p.name)
def test_register_opens_with_a_pointer_to_the_document_that_owns_the_status(register):
    head = banner(register)
    assert "VCRM.md" in head, (
        f"{register.name} does not name docs/VCRM.md in its first {BANNER_LINES} lines. A reader cannot tell which "
        "document to trust for requirement status: add a banner that says VCRM.md is the authority."
    )
    assert re.search(r"authoritative|superseded|point-in-time|snapshot", head, re.I), (
        f"{register.name} names VCRM.md but does not say how the two relate (authoritative / superseded / snapshot)."
    )


@pytest.mark.parametrize("register", REGISTERS, ids=lambda p: p.name)
def test_every_file_a_register_banner_points_to_exists(register):
    head = banner(register)
    named = re.findall(r"`(docs/[^`]+?\.(?:md|txt|csv))`", head)
    linked = re.findall(r"\]\((?!https?:)([^)#\s]+)", head)
    missing = [n for n in named if not (ROOT / n).exists()]
    missing += [link for link in linked if not (register.parent / link).resolve().exists()]
    assert missing == [], f"{register.name} banner points at files that do not exist: {missing}"


@pytest.mark.parametrize("register", REGISTERS, ids=lambda p: p.name)
def test_requirement_status_quoted_in_a_banner_is_the_one_vcrm_gives(register):
    wanted = {"verified": "verified", "deferred": "deferred", "partial": "partial", "not started": "not started"}
    actual = statuses()
    wrong = []
    for br, word in re.findall(r"\b(BR-\d+) \((Verified|Deferred|Partial|Not started)", banner(register)):
        if actual.get(br) != wanted[word.lower()]:
            wrong.append(f"{br}: {register.name} says {word}, VCRM.md says {actual.get(br)}")
    assert wrong == [], wrong


def test_every_oit_id_cited_in_the_registers_or_vcrm_is_an_entry_in_the_tracker():
    tracked = set(re.findall(r"OIT-\d{3}", TRACKER.read_text(encoding="utf-8")))
    assert tracked, "the tracker defines no OIT-nnn entries"
    cited: dict[str, set[str]] = {}
    for doc in [VCRM, RECONCILIATION, *REGISTERS]:
        for oit in re.findall(r"OIT-\d{3}", doc.read_text(encoding="utf-8")):
            cited.setdefault(oit, set()).add(doc.name)
    dangling = {oit: sorted(docs) for oit, docs in cited.items() if oit not in tracked}
    assert dangling == {}, f"cited but not in docs/{TRACKER.name}: {dangling}"


def ddl_table_count(engine: str) -> int:
    """CREATE TABLE statements in an engine's core schema. Teradata writes CREATE SET TABLE; comments are skipped."""
    text = (ROOT / "build" / "schema" / engine / "te_core_schema.sql").read_text(encoding="utf-8")
    return len(re.findall(r"^\s*CREATE\s+(?:SET\s+|MULTISET\s+)?TABLE\b", text, re.M | re.I))


def test_engine_table_counts_in_engine_parity_todo_match_the_ddl():
    rows = dict(re.findall(r"^\| \*\*(\w+)\*\* \| (\d+) \|", ENGINE_PARITY.read_text(encoding="utf-8"), re.M))
    assert {"postgresql", "sqlite", "mariadb", "teradata"} <= set(rows), (
        f"ENGINE_PARITY_TODO.md's 'Measured state' table lost an engine row: {sorted(rows)}"
    )
    wrong = {e: (int(n), ddl_table_count(e)) for e, n in rows.items() if int(n) != ddl_table_count(e)}
    assert wrong == {}, (
        f"engine: (count in ENGINE_PARITY_TODO.md, CREATE TABLE statements in the DDL) = {wrong}. "
        "Count with 'CREATE SET TABLE' as well as 'CREATE TABLE', and skip comment lines."
    )
