"""Per-run VCRM gap report generator.

Reads the run's `summary.json`, joins it against an inline BR catalogue
(extracted from `VCRM.md`), and emits `VCRM_GAPS_<run_id>.md` beside the
summary so every run records the live gap state.

Per-BR status is derived from this run's outcomes:
  - VERIFIED   - at least one covering eval passed; baseline says "full"
  - PARTIAL    - at least one covering eval passed; baseline says "partial"
  - REGRESSION - a covering eval failed (was previously verified)
  - SKIPPED    - all covering evals skipped (e.g. PG unavailable)
  - UNVERIFIED - no covering eval in this run / no covering eval defined
  - OUT-OF-BAND - BR is verified by Python unit tests or SQL suites,
                  not by evals; mention but don't fail
  - DEFERRED   - declared out-of-scope (BR-21, BR-22)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# BR catalogue. Lifted from VCRM.md; keep these in sync if VCRM.md is edited.
# `covering_evals` maps tier letter -> list of scenario folder names.
# `oob_layers` is for BRs verified only by Python unit tests or SQL suites
# (not directly observable by the eval runner).
# --------------------------------------------------------------------------

BR_CATALOGUE: List[Dict[str, Any]] = [
    {
        "id": "BR-01",
        "title": "Multi-environment deployment (Dev/Test/Staging/Prod isolated)",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "partial",
        "notes": "Test/Staging/Prod structural parity not asserted (Tier E gap)",
    },
    {
        "id": "BR-02",
        "title": "Six DB engines supported via adapters",
        "category": "Functional",
        "covering_evals": {},
        "baseline": "gap",
        "notes": "No non-PG engine has any test coverage (Tier X gap)",
    },
    {
        "id": "BR-03",
        "title": "Schema is fully parameterised via \\set",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "Tier S passes --set overrides; if those resolve, parameterisation works",
    },
    {
        "id": "BR-04",
        "title": "12-table T&E data model present",
        "category": "Functional",
        "covering_evals": {
            "i": ["01_deploy_dev_twice"],
            "s": ["01_fresh_deploy_then_all_tests_pass"],
        },
        "baseline": "full",
        "notes": "Tier I counts 11 of 12 tables (evidence_artifacts is schema-only)",
    },
    {
        "id": "BR-05",
        "title": "100% VCRM coverage for CYB9131 + gap detection for LAND400",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 03 contains 23 assertions dedicated to this",
    },
    {
        "id": "BR-06",
        "title": "TEMP versioning (draft -> approved -> superseded)",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 02 sequencing assertions",
    },
    {
        "id": "BR-07",
        "title": "Test result verdict enum + linkage",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 04 verdict assertions",
    },
    {
        "id": "BR-08",
        "title": "DR severity + resolved_at lifecycle",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 04 DR assertions",
    },
    {
        "id": "BR-09",
        "title": "Idempotent deployment",
        "category": "Functional",
        "covering_evals": {
            "i": ["01_deploy_dev_twice"],
            "s": ["01_fresh_deploy_then_all_tests_pass"],
        },
        "baseline": "full",
        "notes": "Tier I is the canonical verifier",
    },
    {
        "id": "BR-10",
        "title": "CSV pre-ingestion validation rejects malformed input",
        "category": "Functional",
        "covering_evals": {
            "p": [
                "02_empty_file", "03_empty_header_only_newline",
                "04_no_valid_rows", "07_column_mismatch_short",
                "08_column_mismatch_long", "19_missing_env_vars",
                "20_missing_csv_file", "23_invalid_utf8_bytes",
            ],
        },
        "baseline": "full",
        "notes": "8 Tier P scenarios + Python unit tests 1, 2, 4, 8 (out-of-band)",
        "oob_layers": ["PU"],
    },
    {
        "id": "BR-11",
        "title": "Valid / skip row separation with reasons",
        "category": "Functional",
        "covering_evals": {
            "p": ["05_mixed_valid_skipped", "09_empty_row", "16_whitespace_only_row"],
        },
        "baseline": "full",
        "notes": "3 Tier P scenarios + Python unit test 3 (out-of-band)",
        "oob_layers": ["PU"],
    },
    {
        "id": "BR-12",
        "title": "Clearance enum {baseline,NV1,NV2,PV}",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 01 personnel assertions",
    },
    {
        "id": "BR-13",
        "title": "ISM classification marking enum",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 02 test_programs assertions",
    },
    {
        "id": "BR-14",
        "title": "Phase type enum (DT&E/AT&E/OT&E/...)",
        "category": "Functional",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "SQL suite 02 phase_type assertions",
    },
    {
        "id": "BR-15",
        "title": "Per-environment connection limits enforced",
        "category": "Functional",
        "covering_evals": {},
        "baseline": "gap",
        "notes": "No test asserts pg_roles.rolconnlimit. 1-hour fix available.",
    },
    {
        "id": "BR-16",
        "title": "Automated single-command regression",
        "category": "Quality",
        "covering_evals": {"p": ["__any__"], "i": ["__any__"], "s": ["__any__"]},
        "baseline": "full",
        "notes": "If the runner produced any per-tier output, this BR is met",
    },
    {
        "id": "BR-17",
        "title": "Graceful degradation when PG unavailable",
        "category": "Quality",
        "covering_evals": {
            "i": ["01_deploy_dev_twice"],
            "s": ["01_fresh_deploy_then_all_tests_pass"],
        },
        "baseline": "full",
        "notes": "A clean SKIP outcome IS the verification - SKIPPED counts as verified here",
        "skip_means_verified": True,
    },
    {
        "id": "BR-18",
        "title": "Machine-readable JSON report per run",
        "category": "Quality",
        "covering_evals": {},
        "baseline": "full",
        "notes": "Implicitly verified: if you're reading this file, summary.json was written",
        "oob_layers": ["PU"],
        "implicitly_verified": True,
    },
    {
        "id": "BR-19",
        "title": "Build/tests/evals physically segregated",
        "category": "Quality",
        "covering_evals": {},
        "baseline": "full",
        "notes": "Verified by Inspection (ARCHITECTURE.md + folder layout)",
        "oob_layers": ["Inspection"],
        "implicitly_verified": True,
    },
    {
        "id": "BR-20",
        "title": "85/85 SQL assertions pass",
        "category": "Quality",
        "covering_evals": {"s": ["01_fresh_deploy_then_all_tests_pass"]},
        "baseline": "full",
        "notes": "Tier S asserts min_total_assertions=85 and pass_rate=100%",
    },
    {
        "id": "BR-21",
        "title": "Cross-engine schema equivalence",
        "category": "Out of scope",
        "covering_evals": {},
        "baseline": "deferred",
        "notes": "Deferred per evals/FAILURE_MODES.md",
    },
    {
        "id": "BR-22",
        "title": "Performance at >= 1M rows",
        "category": "Out of scope",
        "covering_evals": {},
        "baseline": "deferred",
        "notes": "Deferred per evals/HANDOFF.md",
    },
]


# --------------------------------------------------------------------------
# Status computation

STATUS_ICONS = {
    "VERIFIED":    "OK",
    "PARTIAL":     "PARTIAL",
    "REGRESSION":  "REGRESSION",
    "SKIPPED":     "SKIPPED",
    "UNVERIFIED":  "GAP",
    "OUT-OF-BAND": "OOB",
    "DEFERRED":    "DEFERRED",
}


def _scenario_outcome(tier: str, name: str, by_tier: Dict[str, Dict[str, str]]) -> str:
    """Return PASS / FAIL / SKIP / MISSING for a scenario name in a given tier."""
    tier_results = by_tier.get(tier, {})
    if name == "__any__":
        if any(v == "PASS" for v in tier_results.values()):
            return "PASS"
        if any(v == "FAIL" for v in tier_results.values()):
            return "FAIL"
        if tier_results:
            return "SKIP"
        return "MISSING"
    return tier_results.get(name, "MISSING")


def compute_status(br: Dict[str, Any], by_tier: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    baseline = br.get("baseline", "full")

    if baseline == "deferred":
        return {"status": "DEFERRED", "details": []}

    covering = br.get("covering_evals", {})

    if not covering:
        if br.get("implicitly_verified"):
            return {"status": "VERIFIED", "details": ["Implicit (Inspection)"]}
        if baseline == "gap":
            return {"status": "UNVERIFIED", "details": ["No eval covers this BR"]}
        if br.get("oob_layers"):
            return {
                "status": "OUT-OF-BAND",
                "details": ["Verified by " + ", ".join(br["oob_layers"]) + " (not in this run)"],
            }
        return {"status": "UNVERIFIED", "details": ["No covering test"]}

    details: List[str] = []
    any_pass = False
    any_fail = False
    any_skip = False

    for tier, scenarios in covering.items():
        for scenario in scenarios:
            outcome = _scenario_outcome(tier, scenario, by_tier)
            tag = scenario if scenario != "__any__" else "(any scenario)"
            details.append("tier_" + tier + "/" + tag + ": " + outcome)
            if outcome == "PASS":
                any_pass = True
            elif outcome == "FAIL":
                any_fail = True
            elif outcome == "SKIP":
                any_skip = True

    if any_fail:
        return {"status": "REGRESSION", "details": details}
    if any_pass:
        return {
            "status": "PARTIAL" if baseline == "partial" else "VERIFIED",
            "details": details,
        }
    if any_skip:
        if br.get("skip_means_verified"):
            return {"status": "VERIFIED",
                    "details": details + ["Skip is the contract for this BR"]}
        return {"status": "SKIPPED", "details": details}
    return {"status": "UNVERIFIED", "details": details}


# --------------------------------------------------------------------------
# Markdown writer

def _outcomes_by_tier(summary: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    by_tier: Dict[str, Dict[str, str]] = {}
    for sc in summary.get("scenarios", []):
        tier = sc.get("tier", "?")
        name = sc.get("name", "?")
        if sc.get("skipped"):
            outcome = "SKIP"
        elif sc.get("passed"):
            outcome = "PASS"
        else:
            outcome = "FAIL"
        by_tier.setdefault(tier, {})[name] = outcome
    return by_tier


def generate_markdown(summary: Dict[str, Any]) -> str:
    by_tier = _outcomes_by_tier(summary)
    run_id = summary.get("run_id", "unknown")
    started_at = summary.get("started_at", "")
    totals = summary.get("totals", {})

    # Compute status per BR
    rows = []
    counts: Dict[str, int] = {k: 0 for k in STATUS_ICONS}
    for br in BR_CATALOGUE:
        st = compute_status(br, by_tier)
        rows.append((br, st))
        counts[st["status"]] = counts.get(st["status"], 0) + 1

    # Build markdown
    lines: List[str] = []
    lines.append("# VCRM Gap Report - run " + run_id)
    lines.append("")
    lines.append("Generated: " + datetime.now(timezone.utc).isoformat())
    lines.append("Run started: " + started_at)
    lines.append("Tier eval totals: " + json.dumps(totals))
    lines.append("")
    lines.append("Auto-generated by `evals/gap_report.py` at the end of `evals/runner.py`.")
    lines.append("Reflects this run's outcomes only. For the static catalogue see `VCRM.md` and `VCRM_GAPS.md`.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count | Meaning |")
    lines.append("|--------|------:|---------|")
    lines.append("| VERIFIED    | " + str(counts.get("VERIFIED", 0))    + " | Baseline=full and >=1 covering eval passed |")
    lines.append("| PARTIAL     | " + str(counts.get("PARTIAL", 0))     + " | Baseline=partial; some aspects verified |")
    lines.append("| REGRESSION  | " + str(counts.get("REGRESSION", 0))  + " | A covering eval FAILED this run - investigate |")
    lines.append("| SKIPPED     | " + str(counts.get("SKIPPED", 0))     + " | All covering evals skipped (e.g. PG unavailable) |")
    lines.append("| UNVERIFIED  | " + str(counts.get("UNVERIFIED", 0))  + " | No covering eval - this is a real gap |")
    lines.append("| OUT-OF-BAND | " + str(counts.get("OUT-OF-BAND", 0)) + " | Verified by PU/SQL suites, not by evals |")
    lines.append("| DEFERRED    | " + str(counts.get("DEFERRED", 0))    + " | Out-of-scope by project decision |")
    lines.append("")

    # Spotlight any regressions or unverified
    regressions = [(br, st) for br, st in rows if st["status"] == "REGRESSION"]
    unverified  = [(br, st) for br, st in rows if st["status"] == "UNVERIFIED"]
    skipped     = [(br, st) for br, st in rows if st["status"] == "SKIPPED"]

    if regressions:
        lines.append("## REGRESSIONS - investigate before release")
        lines.append("")
        for br, st in regressions:
            lines.append("- **" + br["id"] + "** " + br["title"])
            for d in st["details"]:
                lines.append("  - " + d)
        lines.append("")

    if unverified:
        lines.append("## Unverified - no eval coverage")
        lines.append("")
        for br, st in unverified:
            lines.append("- **" + br["id"] + "** " + br["title"])
            lines.append("  - " + br.get("notes", ""))
        lines.append("")

    if skipped:
        lines.append("## Skipped this run - re-run with PG to verify")
        lines.append("")
        for br, st in skipped:
            lines.append("- **" + br["id"] + "** " + br["title"])
        lines.append("")

    # Full per-BR table
    lines.append("## Per-requirement status (all 22 BRs)")
    lines.append("")
    lines.append("| ID | Status | Title | Evidence (this run) |")
    lines.append("|----|--------|-------|---------------------|")
    for br, st in rows:
        evidence = "; ".join(st["details"]) if st["details"] else "-"
        lines.append("| " + br["id"] +
                     " | " + STATUS_ICONS.get(st["status"], st["status"]) +
                     " | " + br["title"] +
                     " | " + evidence + " |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Companion: `VCRM.md` (catalogue), `VCRM_GAPS.md` (static gap analysis), `TEST_CONDITIONS.md` (every test).")
    # Ensure a single trailing newline so markdownlint MD047 passes.
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Public API

def generate_for_run(run_dir: Path, summary_path: Optional[Path] = None) -> Path:
    """Generate `VCRM_GAPS_<run_id>.md` inside `run_dir`. Returns the path."""
    if summary_path is None:
        summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError("No summary.json at " + str(summary_path))
    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    md = generate_markdown(summary)
    run_id = summary.get("run_id", "unknown")
    out_path = run_dir / ("VCRM_GAPS_" + run_id + ".md")
    with out_path.open("w", encoding="utf-8") as f:
        f.write(md)
    return out_path


# CLI for ad-hoc use (regenerate against an existing summary.json)
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python gap_report.py <path/to/reports/<run_id>/>")
        sys.exit(2)
    run_dir = Path(sys.argv[1])
    out = generate_for_run(run_dir)
    print("Wrote " + str(out))
