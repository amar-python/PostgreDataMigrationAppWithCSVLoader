#!/usr/bin/env python3
"""scripts/security_audit.py: fail CI on a known-vulnerable dependency (#326, SE-05).

Runs pip-audit over every tracked requirements file and `npm audit` over the frontend's production dependencies, then
applies the allow-list in security/audit-allowlist.txt.

Policy
  * Any known vulnerability in a Python dependency blocks. pip-audit does not report a severity, so this is stricter
    than "High or Critical" by design; the allow-list is the way to accept a specific one.
  * An npm vulnerability blocks at High or Critical.
  * An allow-list entry is `<advisory id> <valid-through YYYY-MM-DD> <reason>`. It also matches the advisory's aliases
    (a PYSEC id and its CVE and GHSA names are the same advisory). Once the date passes it stops applying, and an
    expired entry fails the run by itself until it is renewed (with a new reason) or removed.
  * The audit fails CLOSED. If an auditor cannot run, or a requirements file audits no package, the result is "could
    not audit" (exit 2), not a pass.

Exit status: 0 clean, 1 a blocking finding or an expired allow-list entry, 2 could not audit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "security" / "audit-allowlist.txt"
NPM_DIR = "csv-table-hub-main"
NPM_BLOCKING = ("high", "critical")
TIMEOUT = 900


class AuditError(Exception):
    """The audit could not be done. The run must not pass."""


@dataclass(frozen=True)
class Finding:
    source: str
    package: str
    version: str
    advisory: str
    aliases: tuple = ()
    fix: str = ""
    severity: str = ""


@dataclass(frozen=True)
class Allow:
    advisory: str
    expires: dt.date
    reason: str


@dataclass
class Result:
    blocking: list
    allowed: list
    expired: list


def parse_pip_audit(text: str, source: str) -> list[Finding]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuditError(f"pip-audit output for {source} was not JSON: {text[:120]!r}") from exc
    audited = [d for d in data.get("dependencies", []) if "vulns" in d]
    if not audited:
        raise AuditError(f"pip-audit audited no package in {source}")
    findings: dict[tuple, Finding] = {}  # pip-audit can list the same advisory twice for one package
    for dep in audited:
        for vuln in dep["vulns"]:
            finding = Finding(source=source, package=dep["name"], version=dep["version"], advisory=vuln["id"],
                              aliases=tuple(vuln.get("aliases", ())), fix=", ".join(vuln.get("fix_versions") or ()))
            findings.setdefault((finding.package, finding.version, finding.advisory), finding)
    return list(findings.values())


def parse_npm_audit(text: str, source: str) -> list[Finding]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuditError(f"npm audit output for {source} was not JSON: {text[:120]!r}") from exc
    if "error" in data:
        err = data["error"] or {}
        raise AuditError(f"npm audit failed for {source}: {err.get('code', '?')} {err.get('summary', '')}".strip())
    vulns = data.get("vulnerabilities")
    if vulns is None:
        raise AuditError(f"npm audit output for {source} has no 'vulnerabilities' key")
    findings = []
    for name, entry in vulns.items():
        # `via` holds the advisories behind a package (objects) or the packages that pull it in (strings, whose
        # cause is reported under their own name), so only the objects are findings.
        for via in entry.get("via", []):
            if not isinstance(via, dict):
                continue
            severity = via.get("severity") or entry.get("severity", "")
            if severity not in NPM_BLOCKING:
                continue
            advisory = (via.get("url") or "").rstrip("/").rsplit("/", 1)[-1] or str(via.get("source", name))
            findings.append(Finding(source=source, package=name, version=entry.get("range", ""),
                                    advisory=advisory, fix=str(entry.get("fixAvailable", "")),
                                    severity=severity))
    return findings


def parse_allowlist(text: str) -> list[Allow]:
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        try:
            if len(parts) != 3:
                raise ValueError("expected '<advisory id> <valid-through YYYY-MM-DD> <reason>'")
            entries.append(Allow(parts[0], dt.date.fromisoformat(parts[1]), parts[2]))
        except ValueError as exc:
            raise AuditError(f"allow-list line {number} is malformed ({exc}): {line!r}") from exc
    return entries


def evaluate(findings: list[Finding], entries: list[Allow], today: dt.date) -> Result:
    active = {e.advisory.upper() for e in entries if e.expires >= today}
    result = Result(blocking=[], allowed=[], expired=[e for e in entries if e.expires < today])
    for finding in findings:
        names = {finding.advisory.upper(), *(a.upper() for a in finding.aliases)}
        (result.allowed if names & active else result.blocking).append(finding)
    return result


def discover_requirements(root: Path = ROOT) -> list[str]:
    """Every tracked requirements file, so a new one is audited without anyone remembering to add it."""
    out = subprocess.run(["git", "ls-files", "*requirements*.txt"], cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        raise AuditError(f"git ls-files failed: {out.stderr.strip()[:200]}")
    return sorted(line for line in out.stdout.splitlines() if line)


def _run(cmd: list[str], cwd: Path, what: str) -> str:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"{what} could not run: {exc}") from exc
    if done.returncode not in (0, 1) or not done.stdout.strip():  # 1 means "found something", with JSON on stdout
        raise AuditError(f"{what} exited {done.returncode}: {(done.stderr or done.stdout).strip()[-300:]}")
    return done.stdout


def run_pip_audit(requirements: str) -> str:
    return _run([sys.executable, "-m", "pip_audit", "-r", requirements, "--progress-spinner", "off",
                 "--format", "json"], ROOT, f"pip-audit on {requirements}")


def run_npm_audit(directory: str) -> str:
    npm = shutil.which("npm")
    if not npm:
        raise AuditError("npm is not installed, so the frontend's dependencies cannot be audited")
    return _run([npm, "audit", "--omit=dev", "--json"], ROOT / directory, f"npm audit in {directory}")


def main(argv=None, *, pip_runner=run_pip_audit, npm_runner=run_npm_audit, today=None, requirements=None,
         allowlist_text=None, npm_dir=NPM_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    args = parser.parse_args(argv)
    today = today or dt.date.today()
    problems: list[str] = []
    findings: list[Finding] = []
    try:
        entries = parse_allowlist(allowlist_text if allowlist_text is not None
                                  else args.allowlist.read_text(encoding="utf-8"))
        files = requirements if requirements is not None else discover_requirements()
    except (AuditError, OSError) as exc:
        print(f"could not audit: {exc}")
        return 2
    if not files:
        print("could not audit: no requirements files were found")
        return 2
    for path in files:
        try:
            findings += parse_pip_audit(pip_runner(path), path)
        except AuditError as exc:
            problems.append(f"{path}: {exc}")
    try:
        findings += parse_npm_audit(npm_runner(npm_dir), f"{npm_dir} (production)")
    except AuditError as exc:
        problems.append(f"{npm_dir}: {exc}")
    if problems:
        print("could not audit:\n  " + "\n  ".join(problems))
        return 2

    result = evaluate(findings, entries, today)
    for f in result.allowed:
        print(f"allowed   {f.package} {f.version}  {f.advisory}  ({f.source})")
    for e in result.expired:
        print(f"expired allow-list entry: {e.advisory} was valid through {e.expires}; renew it with a new reason, "
              "or remove it")
    for f in result.blocking:
        print(f"BLOCKING  {f.package} {f.version}  {f.advisory}  fix: {f.fix or 'none known'}  ({f.source})")
    if result.blocking or result.expired:
        print(f"\n{len(result.blocking)} blocking, {len(result.expired)} expired exception(s). Upgrade the package, "
              "or add an entry to security/audit-allowlist.txt with a reason and an expiry date.")
        return 1
    print(f"no known vulnerabilities in {len(files)} requirements file(s) or in {npm_dir}'s production dependencies"
          + (f" ({len(result.allowed)} allowed)" if result.allowed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
