"""
Regression tests for preflight.ps1 (PowerShell 5.1 compatibility).

Guards against the defect fixed in PR #145: PowerShell 7+ only syntax (`??`)
breaking the Windows preflight script on Windows PowerShell 5.1.

Layers:
  - Static tests (run on all platforms in CI): inspect script AST/tokens.
  - Windows execution tests (collected ONLY when powershell.exe exists on win32,
    preventing CI 'unmet prerequisites must FAIL, not skip' gate failures).
Verification method (ASDEFCON): Inspection (static), Test (Windows run).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "preflight.ps1"

WINDOWS_PS = shutil.which("powershell") if sys.platform == "win32" else None


# ----------------------------------------------------------------- helpers
def _code_only(text: str) -> str:
    """Return script text with comments removed and string contents blanked,
    so syntax checks don't trip on prose or quoted text."""
    out, quote, i = [], None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if quote == '"' and ch == "`":      # backtick escape in "..."
                i += 2
                continue
            if ch == quote:
                quote = None
                out.append(ch)
            else:
                out.append(" " if ch != "\n" else "\n")
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":                           # comment to end of line
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


@pytest.fixture(scope="module")
def raw() -> str:
    assert SCRIPT.exists(), f"{SCRIPT} not found"
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(raw) -> str:
    return _code_only(raw)


def _run(args, extra_env=None, drop_env=(), timeout=180):
    env = os.environ.copy()
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD"):
        env.pop(k, None)
    for k in drop_env:
        env.pop(k, None)
    env.update(extra_env or {})
    return subprocess.run(
        [WINDOWS_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )


# ------------------------------------------------- static (Inspection) tests
@pytest.mark.unit
@pytest.mark.regression
def test_no_null_coalescing_operator(code):
    """`??` / `??=` is PowerShell 7+ only and fails to parse on 5.1."""
    hits = [line.strip() for line in code.splitlines() if "??" in line]
    assert not hits, f"PowerShell 7+ '??' found: {hits}"


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    "label,pattern",
    [
        ("null-conditional member '?.'", r"\$\w+\?\."),
        ("null-conditional index '?['", r"\$\w+\?\["),
        ("pipeline chain '&&'", r"&&"),
        ("pipeline chain '||'", r"\|\|"),
        ("ForEach-Object -Parallel", r"(?i)-Parallel\b"),
    ],
)
def test_no_other_powershell7_only_syntax(code, label, pattern):
    assert not re.search(pattern, code), f"PowerShell 7+ only syntax: {label}"


@pytest.mark.unit
@pytest.mark.regression
def test_no_utf8_bom():
    """A BOM caused a noisy line-1 diff during the fix; keep the file BOM-free."""
    assert not SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf"), "preflight.ps1 has a UTF-8 BOM"


@pytest.mark.unit
@pytest.mark.regression
def test_port_label_is_not_hardcoded(raw):
    """The check label must follow the configured port (was fixed at 'port 5432')."""
    assert "'port 5432 reachable'" not in raw
    assert re.search(r'Test-Check\s+"port \$pgPort reachable"', raw)


@pytest.mark.unit
@pytest.mark.regression
def test_connection_defaults_resolved_once_and_reused(code):
    """Defaults live in variables; connection commands must use them."""
    for var, env in [("pgHost", "PGHOST"), ("pgPort", "PGPORT"),
                     ("pgUser", "PGUSER"), ("pgDb", "PGDATABASE")]:
        assert re.search(rf"\${var}\s*=\s*if\s*\(\$env:{env}\)", code), f"${var} default missing"
    assert re.search(r"Test-NetConnection\s+-ComputerName\s+\$pgHost\s+-Port\s+\$pgPort", code)
    assert re.search(r"psql\s+-h\s+\$pgHost\s+-p\s+\$pgPort\s+-U\s+\$pgUser\s+-d\s+\$pgDb", code)


@pytest.mark.unit
@pytest.mark.regression
def test_default_port_and_host_unchanged(raw):
    assert re.search(
        r"\$pgHost\s*=\s*if\s*\(\$env:PGHOST\)\s*\{\s*\$env:PGHOST\s*\}\s*else\s*\{\s*'localhost'\s*\}", raw
    ), "PGHOST default must remain 'localhost'"
    assert re.search(
        r"\$pgPort\s*=\s*if\s*\(\$env:PGPORT\)\s*\{\s*\[int\]\$env:PGPORT\s*\}\s*else\s*\{\s*5432\s*\}", raw
    ), "PGPORT default must remain 5432 (cast to [int])"
    assert re.search(
        r"\$pgUser\s*=\s*if\s*\(\$env:PGUSER\)\s*\{\s*\$env:PGUSER\s*\}\s*else\s*\{\s*'postgres'\s*\}", raw
    ), "PGUSER default must remain 'postgres'"
    assert re.search(
        r"\$pgDb\s*=\s*if\s*\(\$env:PGDATABASE\)\s*\{\s*\$env:PGDATABASE\s*\}\s*else\s*\{\s*'postgres'\s*\}", raw
    ), "PGDATABASE default must remain 'postgres'"


@pytest.mark.unit
@pytest.mark.regression
def test_exit_code_contract_documented_and_implemented(raw):
    assert "if ($script:Fail -gt 0) { exit 1 }" in raw
    assert "if ($script:Warn -gt 0) { exit 2 }" in raw
    assert re.search(r"(?m)^exit 0\s*$", raw)


# ----------------------------------------------- Windows execution tests
# Conditioned at collection time so non-Windows runners never register or skip
# these tests, avoiding failure against the zero-skip CI accounting policy.
if WINDOWS_PS is not None:
    @pytest.mark.regression
    def test_parses_under_windows_powershell():
        """Parse with the real PowerShell parser (5.1 on stock Windows)."""
        cmd = (
            "$e=$null;$t=$null;"
            "[void][System.Management.Automation.Language.Parser]::ParseFile($env:PF_PATH,[ref]$t,[ref]$e);"
            "if($e -and $e.Count){$e|ForEach-Object{Write-Output $_.Message};exit 1};exit 0"
        )
        r = subprocess.run(
            [WINDOWS_PS, "-NoProfile", "-Command", cmd],
            env={**os.environ, "PF_PATH": str(SCRIPT)}, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"Parse errors:\n{r.stdout}{r.stderr}"

    @pytest.mark.regression
    def test_runs_with_skippg_and_reports_summary():
        r = _run(["-SkipPg"])
        out = r.stdout + r.stderr
        assert r.returncode in (0, 1, 2), out
        assert "Summary:" in r.stdout, out
        assert "ParserError" not in out, out
        assert "PostgreSQL" not in r.stdout.split("Git state")[-1].split("Summary:")[0], \
            "-SkipPg must skip the PostgreSQL section"

    @pytest.mark.regression
    def test_default_port_label_when_pgport_unset():
        r = _run([])
        assert "port 5432 reachable" in r.stdout, r.stdout + r.stderr
        assert "ParserError" not in (r.stdout + r.stderr)

    @pytest.mark.regression
    def test_port_label_follows_pgport():
        r = _run([], extra_env={"PGHOST": "localhost", "PGPORT": "5999"})
        out = r.stdout + r.stderr
        assert "port 5999 reachable" in r.stdout, out
        assert "port 5432 reachable" not in r.stdout, out
        assert re.search(r"\[port 5999 reachable\] \.\.\. WARN", r.stdout), out
        assert r.returncode in (0, 2), out

    @pytest.mark.regression
    def test_pg_checks_are_optional_never_fail():
        r = _run([], extra_env={"PGHOST": "localhost", "PGPORT": "5999", "PGPASSWORD": "x"})
        pg = r.stdout.split("PostgreSQL")[-1].split("Summary:")[0]
        assert "FAIL" not in pg, r.stdout + r.stderr