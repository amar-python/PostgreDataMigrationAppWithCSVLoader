"""Compare axe-core results with the recorded baseline of known violations (#168).

The frontend has accessibility problems today, and fixing them is a separate piece
of work (see tests/accessibility/README.md). A scan that simply fails on any violation
would keep the accessibility job red until then, so nobody would look at it. Instead the
violations that exist now are written down in ``known_violations.json`` and the scan
fails on a *change*:

* a rule that fails on a page where it is not in the baseline, or on more elements than
  the baseline records, is NEW  -> the test fails (a regression);
* a baseline entry whose rule no longer fails at all is FIXED -> the test fails until the
  entry is deleted, so the baseline can only get shorter;
* fewer elements than recorded is only reported (lower the number when convenient).

Pure functions, no browser and no Playwright import: tests/unit/test_a11y_baseline.py
covers them in the free tier.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASELINE_PATH = Path(__file__).with_name("known_violations.json")

# WCAG 2.1 level A and AA: the rule tags axe-core is asked to run.
WCAG_21_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

Baseline = dict[tuple[str, str], dict]


@dataclass
class Outcome:
    new: list[str] = field(default_factory=list)       # regressions: fail
    fixed: list[str] = field(default_factory=list)     # stale baseline entries: fail
    shrunk: list[str] = field(default_factory=list)    # fewer elements than recorded: notice
    known: list[str] = field(default_factory=list)     # as recorded: notice

    @property
    def ok(self) -> bool:
        return not self.new and not self.fixed


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    """The baseline keyed by (scenario, rule id)."""
    entries = json.loads(path.read_text(encoding="utf-8"))["violations"]
    baseline: Baseline = {}
    for entry in entries:
        key = (entry["scenario"], entry["rule"])
        if key in baseline:
            raise ValueError(f"{path.name}: {key[1]} is listed twice for scenario {key[0]!r}")
        if not isinstance(entry.get("nodes"), int) or entry["nodes"] < 1:
            raise ValueError(f"{path.name}: {key} needs a positive integer 'nodes'")
        if not entry.get("note"):
            raise ValueError(f"{path.name}: {key} needs a 'note' saying what is wrong")
        baseline[key] = entry
    return baseline


def describe(violation: dict, limit: int = 3) -> str:
    """One violation as a few readable lines: rule, impact, count, and where."""
    nodes = violation["nodes"]
    lines = [f"{violation['id']} ({violation.get('impact') or 'n/a'}) on {len(nodes)} element(s): "
             f"{violation['help']}"]
    for node in nodes[:limit]:
        target = " ".join(str(t) for t in node["target"])
        html = " ".join(node.get("html", "").split())
        lines.append(f"    {target}\n      {html[:140]}")
    if len(nodes) > limit:
        lines.append(f"    ... and {len(nodes) - limit} more")
    lines.append(f"    {violation.get('helpUrl', '')}")
    return "\n".join(lines)


def compare(scenario: str, violations: list[dict], baseline: Baseline) -> Outcome:
    """Classify the violations found in one scenario against the baseline."""
    out = Outcome()
    found = {v["id"]: v for v in violations}

    for rule, v in sorted(found.items()):
        count = len(v["nodes"])
        entry = baseline.get((scenario, rule))
        if entry is None:
            out.new.append(f"NEW {describe(v)}")
        elif count > entry["nodes"]:
            out.new.append(f"MORE ELEMENTS than the baseline's {entry['nodes']}: {describe(v)}")
        elif count < entry["nodes"]:
            out.shrunk.append(f"{rule}: {count} element(s), baseline records {entry['nodes']}")
        else:
            out.known.append(f"{rule}: {count} element(s), known ({entry['note']})")

    for (scen, rule), entry in sorted(baseline.items()):
        if scen == scenario and rule not in found:
            out.fixed.append(f"{rule} no longer fails here: delete its entry from known_violations.json "
                             f"(it recorded: {entry['note']})")
    return out
