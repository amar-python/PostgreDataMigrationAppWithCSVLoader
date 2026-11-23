"""CI speed-up: splitting the test files across parallel jobs (scripts/ci_shards.py).

The integration job ran the whole suite, then the system tests again, then the whole suite a third time for coverage,
one after the other: 25 to 40 minutes. The suite is now split by test file into shards that run in parallel, each on its
own PostgreSQL service (the system tests share databases and assume a fresh one, so they cannot share a server).

What must hold, or a test would silently stop running:
  * every test file ``pytest`` collects (accessibility excluded: it has its own job) is in exactly one shard, for any
    number of shards, and the files the script lists are the files pytest really collects;
  * the split is deterministic, balanced by recorded duration, and a file with no recorded duration still lands in a
    shard (a new test file is never dropped);
  * the recorded durations name files that exist, so the table cannot rot;
  * the durations can be regenerated from a JUnit report.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci_shards.py"

sys.path.insert(0, str(ROOT / "scripts"))
try:
    import ci_shards  # noqa: E402
finally:
    sys.path.pop(0)


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


# -- every test file is in exactly one shard --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 5, 8])
def test_the_shards_are_disjoint_and_together_hold_every_file(n):
    files = ci_shards.test_files()
    shards = ci_shards.assign(files, ci_shards.load_weights(), n)
    assert len(shards) == n
    flat = [f for shard in shards for f in shard]
    assert sorted(flat) == sorted(files), "every file exactly once"
    assert len(flat) == len(set(flat)), "no file in two shards"


def test_the_files_the_script_lists_are_the_files_pytest_collects():
    """The strongest guard: the script's idea of 'a test file' is checked against pytest's own collection."""
    # `-o addopts=` because pytest.ini already adds -q, and a second one switches the output to per-file counts.
    done = subprocess.run([sys.executable, "-m", "pytest", "tests", "-m", "not accessibility", "--collect-only", "-q",
                           "-o", "addopts=", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True,
                          timeout=300)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    collected = {line.split("::")[0] for line in done.stdout.splitlines() if "::" in line}
    assert len(collected) > 50, f"the collection output was not parsed (got {len(collected)} files): {done.stdout[:300]}"
    listed = set(ci_shards.test_files())
    assert collected <= listed, f"collected by pytest but in no shard: {sorted(collected - listed)}"
    assert listed - collected <= {f for f in listed if _nothing_to_collect_here(f)}, (
        f"listed but pytest collects nothing from them: {sorted(listed - collected)}")


def _nothing_to_collect_here(rel: str) -> bool:
    """A file with no tests, or whose tests tests/conftest.py deselects unless the egress firewall is up (#310)."""
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    return "def test_" not in text or "mark.egress_network" in text


def test_the_accessibility_tests_are_not_in_any_shard():
    assert not [f for f in ci_shards.test_files() if f.startswith("tests/accessibility/")]


def test_helpers_and_caches_are_not_test_files():
    files = ci_shards.test_files()
    assert not [f for f in files if "__pycache__" in f or f.endswith("conftest.py") or "/__init__" in f]
    assert all(f.startswith("tests/") and f.endswith(".py") for f in files)


# -- the split ---------------------------------------------------------------------------------------------------------

def test_the_split_is_deterministic():
    files, weights = ci_shards.test_files(), ci_shards.load_weights()
    assert ci_shards.assign(files, weights, 3) == ci_shards.assign(list(reversed(files)), weights, 3)


def test_the_split_is_balanced_by_recorded_duration():
    files, weights = ci_shards.test_files(), ci_shards.load_weights()
    shards = ci_shards.assign(files, weights, ci_shards.SHARDS)
    totals = [sum(weights.get(f, ci_shards.DEFAULT_WEIGHT) for f in shard) for shard in shards]
    average = sum(totals) / len(totals)
    biggest_file = max(weights.get(f, ci_shards.DEFAULT_WEIGHT) for f in files)
    assert max(totals) <= max(average * 1.25, average + biggest_file), (
        f"unbalanced: {totals} (average {average:.0f}s, biggest file {biggest_file:.0f}s)")
    assert all(shard for shard in shards), "no shard may be empty"


def test_the_heaviest_files_are_spread_not_piled_into_one_shard():
    weights = {"tests/a.py": 100, "tests/b.py": 100, "tests/c.py": 100, "tests/d.py": 1, "tests/e.py": 1, "tests/f.py": 1}
    shards = ci_shards.assign(sorted(weights), weights, 3)
    assert sorted(sum(weights[f] for f in shard) for shard in shards) == [2, 101, 101] or all(
        sum(weights[f] for f in shard) >= 100 for shard in shards)
    assert all(any(weights[f] == 100 for f in shard) for shard in shards), shards


def test_a_file_with_no_recorded_duration_still_lands_in_a_shard():
    files = ["tests/known.py", "tests/brand_new.py"]
    shards = ci_shards.assign(files, {"tests/known.py": 500}, 2)
    flat = [f for shard in shards for f in shard]
    assert sorted(flat) == sorted(files)
    new_shard = next(s for s in shards if "tests/brand_new.py" in s)
    assert "tests/known.py" not in new_shard, "the new file goes to the lighter shard"


def test_one_shard_is_the_whole_suite():
    files = ci_shards.test_files()
    assert ci_shards.assign(files, ci_shards.load_weights(), 1) == [sorted(files)]


# -- the recorded durations --------------------------------------------------------------------------------------------

def test_the_recorded_durations_name_files_that_exist():
    weights = ci_shards.load_weights()
    assert weights, "ci/shard_weights.json must not be empty"
    missing = [f for f in weights if not (ROOT / f).is_file()]
    assert not missing, f"durations recorded for files that no longer exist (regenerate them): {missing}"
    assert all(isinstance(v, (int, float)) and v > 0 for v in weights.values())


def test_the_durations_cover_most_files_so_the_split_is_not_a_guess():
    files, weights = ci_shards.test_files(), ci_shards.load_weights()
    unknown = [f for f in files if f not in weights]
    assert len(unknown) <= max(3, len(files) // 10), f"too many files without a duration: {unknown}"


def test_durations_are_regenerated_from_a_junit_report(tmp_path):
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_one.py").write_text("def test_a(): pass\n")
    (tmp_path / "tests" / "unit" / "test_two.py").write_text("def test_b(): pass\n")
    xml = tmp_path / "junit.xml"
    xml.write_text(textwrap.dedent("""\
        <testsuites><testsuite>
          <testcase classname="tests.unit.test_one" name="test_a" time="1.5"/>
          <testcase classname="tests.unit.test_one.TestK" name="test_b" time="2.25"/>
          <testcase classname="tests.unit.test_two" name="test_c" time="10"/>
          <testcase classname="tests.nowhere.test_gone" name="test_d" time="99"/>
        </testsuite></testsuites>"""))
    weights = ci_shards.weights_from_junit(xml, root=tmp_path)
    assert weights == {"tests/unit/test_one.py": 3.75, "tests/unit/test_two.py": 10.0}


def test_a_file_that_took_no_time_still_costs_its_import_and_collection(tmp_path):
    """Files whose tests are all deselected (or instant) record 0 s; a zero would let one shard take them all for free."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_quick.py").write_text("def test_a(): pass\n")
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuites><testsuite><testcase classname="tests.test_quick" name="test_a" time="0.001"/>'
                   '</testsuite></testsuites>')
    weights = ci_shards.weights_from_junit(xml, root=tmp_path)
    assert weights == {"tests/test_quick.py": ci_shards.MIN_WEIGHT} and ci_shards.MIN_WEIGHT >= 1.0


# -- the command line the workflow uses --------------------------------------------------------------------------------

def test_the_cli_prints_one_shards_files_one_per_line():
    files, weights = ci_shards.test_files(), ci_shards.load_weights()
    expected = ci_shards.assign(files, weights, 3)[1]
    done = cli("files", "--shard", "2", "--of", "3")
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == expected


def test_the_cli_shards_one_to_n_together_are_every_file():
    seen: list[str] = []
    for k in (1, 2, 3):
        done = cli("files", "--shard", str(k), "--of", "3")
        assert done.returncode == 0, done.stderr
        seen += done.stdout.split()
    assert sorted(seen) == sorted(ci_shards.test_files())


@pytest.mark.parametrize("shard, of", [("0", "3"), ("4", "3"), ("-1", "3"), ("1", "0"), ("x", "3")])
def test_the_cli_refuses_a_shard_that_does_not_exist(shard, of):
    done = cli("files", "--shard", shard, "--of", of)
    assert done.returncode != 0, "a typo in the workflow must fail the job, not run nothing and pass"
    assert done.stdout.strip() == ""


def test_the_cli_plan_prints_every_shard_with_an_estimate():
    done = cli("plan", "--of", "3")
    assert done.returncode == 0, done.stderr
    assert all(f"shard {k}" in done.stdout.lower() for k in (1, 2, 3)), done.stdout


def test_the_cli_writes_regenerated_durations(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuites><testsuite><testcase classname="tests.unit.test_ci_shards" name="x" time="4"/>'
                   '</testsuite></testsuites>')
    out = tmp_path / "weights.json"
    done = cli("update-weights", str(xml), "--output", str(out))
    assert done.returncode == 0, done.stderr
    assert json.loads(out.read_text()) == {"tests/unit/test_ci_shards.py": 4.0}
