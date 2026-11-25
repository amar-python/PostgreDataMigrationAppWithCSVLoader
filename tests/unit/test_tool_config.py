"""#323, #324: the tool configuration agrees with itself and with CI.

The lint options are written in two places, because flake8 does not read pyproject.toml: .flake8 (editors and the
pre-commit hook) and scripts/lint.sh (CI). The secret scan's version is in .pre-commit-config.yaml and in
security-scan.yml. The type check is configured in pyproject.toml and run by `make typecheck` from the free-tier job.
These tests fail when one copy changes and the other does not, or when the type check is quietly switched off.
"""

from __future__ import annotations

import configparser
import re
import shlex
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _flake8_options_in_lint_sh() -> dict[str, str]:
    text = (ROOT / "scripts" / "lint.sh").read_text(encoding="utf-8")
    call = re.search(r"python3 -m flake8 (.*?)(?:; then|\n\s*then)", text, re.S)
    assert call, "scripts/lint.sh no longer runs `python3 -m flake8 ...`; update this test with it"
    words = shlex.split(call.group(1).replace("\\\n", " "))
    return dict(w[2:].split("=", 1) for w in words if w.startswith("--") and "=" in w)


def test_flake8_config_matches_the_ci_lint():
    cfg = configparser.ConfigParser()
    assert cfg.read(ROOT / ".flake8"), ".flake8 is missing"
    in_file = {k: v.replace(" ", "") for k, v in cfg["flake8"].items()}
    in_ci = _flake8_options_in_lint_sh()
    assert in_ci, "found no --option=value flags on scripts/lint.sh's flake8 call"
    assert in_file == in_ci, f".flake8 {in_file} differs from scripts/lint.sh {in_ci}"


def _pre_commit() -> dict:
    return yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))


def _hook_ids() -> set[str]:
    return {h["id"] for repo in _pre_commit()["repos"] for h in repo["hooks"]}


def test_pre_commit_runs_the_checks_324_asks_for():
    assert {"flake8", "bandit", "gitleaks", "mypy", "gap-registers"} <= _hook_ids()


def test_pre_commit_gitleaks_is_the_version_ci_runs():
    rev = next(r["rev"] for r in _pre_commit()["repos"] if r["repo"].endswith("/gitleaks/gitleaks"))
    ci = (ROOT / ".github" / "workflows" / "security-scan.yml").read_text(encoding="utf-8")
    images = set(re.findall(r"ghcr\.io/gitleaks/gitleaks:(v[\d.]+)", ci))
    assert images == {rev}, f"pre-commit runs gitleaks {rev}, security-scan.yml runs {sorted(images)}"


def test_pre_commit_bandit_skips_the_test_code_ci_skips():
    bandit = next(h for r in _pre_commit()["repos"] for h in r["hooks"] if h["id"] == "bandit")
    assert "-ll" in bandit["args"], "the CI lint reports medium severity and up (bandit -ll)"
    assert re.match(bandit["exclude"], "tests/unit/x.py") and re.match(bandit["exclude"], "e2e/x.py")
    assert not re.match(bandit["exclude"], "api/main.py")


def _mypy() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]


def test_type_check_covers_every_python_package_ci_measures():
    """The same four as the coverage scope (.coveragerc): the API, the Streamlit app, the validator and the evals."""
    assert set(_mypy()["files"]) >= {"api", "streamlit_app", "build/csv", "evals"}


def test_type_check_is_not_silenced():
    """An exemption names a module that has no type information; nothing turns errors off wholesale."""
    mypy = _mypy()
    assert not mypy.get("ignore_missing_imports"), "ignore_missing_imports applies to every module; list modules"
    assert not mypy.get("ignore_errors")
    assert mypy.get("warn_unused_ignores"), "a `# type: ignore` that no longer hides anything must be reported"
    for override in mypy.get("overrides", []):
        modules = override["module"] if isinstance(override["module"], list) else [override["module"]]
        assert not override.get("ignore_errors"), f"errors are switched off for {modules}"
        assert not override.get("disable_error_code"), f"error codes are switched off for {modules}"
        if override.get("ignore_missing_imports"):
            ours = [m for m in modules if m.split(".")[0] in ("api", "streamlit_app")]
            assert not ours, f"missing imports are ignored for our own modules {ours}"


# Every flag `mypy --strict` turns on (mypy 2.x), split between the global section and the api/ override.
STRICT_GLOBAL = {"warn_unused_configs", "warn_unused_ignores", "warn_redundant_casts", "strict_equality",
                 "extra_checks", "check_untyped_defs"}
STRICT_API = {"no_implicit_reexport", "disallow_untyped_decorators", "disallow_untyped_defs",
              "disallow_incomplete_defs", "disallow_any_generics", "disallow_untyped_calls",
              "disallow_subclassing_any", "warn_return_any"}


def test_every_package_gets_the_strict_flags_that_need_no_annotations():
    mypy = _mypy()
    assert {f for f in STRICT_GLOBAL if mypy.get(f) is True} == STRICT_GLOBAL


def test_api_is_checked_with_the_whole_of_strict():
    """#323: api/ is strict. Switching a flag off again has to change this test too."""
    api = next(o for o in _mypy()["overrides"] if "api" in o["module"])
    assert {f for f in STRICT_API if api.get(f) is True} == STRICT_API


def test_the_loader_result_type_declares_every_key_the_loaders_set():
    """The point of LoadResult (#323): a key a loader or the route sets must be declared, or mypy is not checking it.

    mypy enforces this for literals; this catches keys set through a variable name mypy cannot see, by reading the
    keyword arguments and literal keys in the result builders' callers.
    """
    import ast
    from typing import get_type_hints

    from api.services.results import LoadResult

    declared = set(get_type_hints(LoadResult))
    used: set[str] = set()
    trees = [ast.parse((ROOT / path).read_text(encoding="utf-8")) for path in (
        "api/services/dynamic_loader.py", "api/services/te_loader.py", "api/services/load_common.py",
        "api/services/staged_import.py")]
    # Only the upload route: the preview route also calls its dict `result`, but that is build_preview's shape.
    routes = ast.parse((ROOT / "api/routers/csv_routes.py").read_text(encoding="utf-8"))
    trees += [n for n in ast.walk(routes) if isinstance(n, ast.FunctionDef) and n.name == "upload"]
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("ok_result", "rows_failed"):
                used |= {k.arg for k in node.keywords if k.arg}
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "result" and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                used.add(node.slice.value)
    assert used, "found no result keys; the loaders' structure changed, so update this test"
    assert used <= declared, f"set but not declared in LoadResult: {sorted(used - declared)}"


def test_ci_runs_the_type_check():
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "quality-gate.yml").read_text(encoding="utf-8"))["jobs"]
    runs = [s.get("run", "") for s in jobs["free-tier"]["steps"]]
    assert "make typecheck" in runs, "the free-tier job must run `make typecheck`"
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = re.search(r"^typecheck:\n\t(.+)$", makefile, re.M)
    assert target and target.group(1).strip() == "python3 -m mypy", "`make typecheck` runs mypy from its config"
