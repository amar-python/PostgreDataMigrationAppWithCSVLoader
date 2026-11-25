"""Supply chain and reproducible builds: #325 (SE-04), #327 (SE-06), #328 (SE-07), #329 (SE-08).

  #325  every action is pinned to a full commit SHA with its version in a comment; every workflow has a read-only
        token by default; Dependabot covers pip, github-actions, npm and docker.
  #327  Python installs come from hashed lock files that agree with each other and with the requirements files they
        were compiled from; the frontend has one JS lock file; every base image is pinned by digest; the API and
        frontend images have a HEALTHCHECK.
  #328  Python 3.12 is the one supported version, and CI, the Dockerfiles, preflight and the offline bundle agree.
  #329  a CI job runs the frontend's lint, type-check and build.

No database or network needed: these read the files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
DOCKERFILES = sorted([*(ROOT / "container").glob("*.Dockerfile"), ROOT / "infra/Dockerfile"])
SUPPORTED_PYTHON = "3.12"

# lock file -> the requirements files it is compiled from (scripts/lock_requirements.sh)
LOCKS = {
    "api/requirements.lock": ["api/requirements.txt"],
    "streamlit_app/requirements.lock": ["streamlit_app/requirements.txt"],
    "requirements-dev.lock": ["requirements-dev.txt", "api/requirements.txt"],
    "requirements-a11y.lock": ["requirements-dev.txt", "api/requirements.txt", "requirements-a11y.txt",
                               "streamlit_app/requirements.txt"],
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow(path: Path) -> dict:
    return yaml.safe_load(_text(path))


def _steps():
    for path in WORKFLOWS:
        for job_id, job in _workflow(path)["jobs"].items():
            for step in job.get("steps", []):
                yield path.name, job_id, step


# ── #325 ──────────────────────────────────────────────────────────────────────

def test_every_action_is_pinned_to_a_commit_sha_with_its_version_in_a_comment():
    offenders = []
    for path in WORKFLOWS:
        for line in _text(path).splitlines():
            m = re.match(r"\s*(?:-\s*)?uses:\s*(\S+)(.*)$", line)
            if not m or m.group(1).startswith("./"):
                continue
            ok = re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)) and re.fullmatch(
                r"\s+#\s*v\d+(\.\d+){0,2}\s*", m.group(2))
            if not ok:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, "pin actions as owner/repo@<40-hex sha> # vX.Y.Z: " + "; ".join(offenders)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_defaults_to_a_read_only_token(path):
    assert _workflow(path).get("permissions") == {"contents": "read"}, f"{path.name}: set permissions: contents: read"


def test_dependabot_covers_pip_actions_npm_and_docker():
    updates = yaml.safe_load(_text(ROOT / ".github/dependabot.yml"))["updates"]
    dirs: dict[str, set[str]] = {}
    for u in updates:
        dirs.setdefault(u["package-ecosystem"], set()).update(u.get("directories") or [u["directory"]])
    assert "/" in dirs.get("pip", set())
    assert "/" in dirs.get("github-actions", set())
    assert "/csv-table-hub-main" in dirs.get("npm", set())
    assert {"/container", "/infra"} <= dirs.get("docker", set())


# ── #328 ──────────────────────────────────────────────────────────────────────

def test_python_version_file_names_the_supported_version():
    assert _text(ROOT / ".python-version").strip() == SUPPORTED_PYTHON


def test_every_ci_python_comes_from_the_version_file():
    setups = [(wf, job, s) for wf, job, s in _steps() if str(s.get("uses", "")).startswith("actions/setup-python@")]
    assert setups, "expected setup-python steps"
    for wf, job, step in setups:
        with_ = step.get("with") or {}
        assert with_.get("python-version-file") == ".python-version", f"{wf}/{job}: use python-version-file"
        assert "python-version" not in with_, f"{wf}/{job}: a second Python version"


def test_every_python_base_image_is_the_supported_version():
    images = [ins for p in DOCKERFILES for ins in _text(p).splitlines() if re.match(r"FROM\s+python:", ins)]
    assert images, "expected a python base image"
    for ins in images:
        assert re.match(rf"FROM\s+python:{re.escape(SUPPORTED_PYTHON)}-slim@sha256:", ins), ins


def test_the_offline_bundle_downloads_wheels_for_the_supported_version():
    versions = re.findall(r"--python-version\s+(\S+)", _text(ROOT / "scripts/offline/build_bundle.sh"))
    assert versions and set(versions) == {SUPPORTED_PYTHON}
    assert f"python{SUPPORTED_PYTHON}" in _text(ROOT / "scripts/offline/install.sh")


def test_preflight_requires_the_supported_version():
    major, minor = SUPPORTED_PYTHON.split(".")
    assert f"sys.version_info >= ({major},{minor})" in _text(ROOT / "preflight.sh")
    assert f"[int]$parts[1] -ge {minor}" in _text(ROOT / "preflight.ps1")


def test_the_locks_are_compiled_for_the_supported_version():
    assert re.search(rf"^PY={re.escape(SUPPORTED_PYTHON)}$", _text(ROOT / "scripts/lock_requirements.sh"), re.M)


# ── #327: Python locks ────────────────────────────────────────────────────────

def _lock_entries(path: str) -> dict[str, tuple[str, int]]:
    """name -> (version, number of hashes)."""
    entries: dict[str, tuple[str, int]] = {}
    current = None
    for line in _text(ROOT / path).splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;\\]+)", line)
        if m:
            current = canonicalize_name(m.group(1).split("[")[0])
            entries[current] = (m.group(2), 0)
        elif current and "--hash=sha256:" in line:
            version, n = entries[current]
            entries[current] = (version, n + 1)
    return entries


def _direct_requirements(path: str) -> list[Requirement]:
    reqs = []
    for line in _text(ROOT / path).splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            reqs.append(Requirement(line))
    return reqs


@pytest.mark.parametrize("lock", sorted(LOCKS))
def test_every_lock_entry_is_hashed(lock):
    entries = _lock_entries(lock)
    assert entries, f"{lock} has no entries"
    unhashed = [name for name, (_, n) in entries.items() if n == 0]
    assert not unhashed, f"{lock}: entries without a hash: {unhashed}"


@pytest.mark.parametrize("lock", sorted(LOCKS))
def test_each_lock_satisfies_the_requirements_files_it_was_compiled_from(lock):
    """A requirements file changed (by hand or by Dependabot) without a re-lock fails here:
    run `bash scripts/lock_requirements.sh`."""
    entries = _lock_entries(lock)
    for source in LOCKS[lock]:
        for req in _direct_requirements(source):
            name = canonicalize_name(req.name)
            assert name in entries, f"{lock} lacks {req.name} from {source}: re-run scripts/lock_requirements.sh"
            version = entries[name][0]
            assert req.specifier.contains(version, prereleases=True), (
                f"{lock} has {req.name}=={version}, which {source} ({req}) no longer allows: re-run "
                "scripts/lock_requirements.sh")


def test_a_package_has_the_same_version_in_every_lock():
    seen: dict[str, dict[str, str]] = {}
    for lock in LOCKS:
        for name, (version, _) in _lock_entries(lock).items():
            seen.setdefault(name, {})[lock] = version
    disagree = {name: v for name, v in seen.items() if len(set(v.values())) > 1}
    assert not disagree, f"the locks disagree (CI and the images would run different code): {disagree}"


def test_ci_installs_python_packages_only_from_hashed_locks():
    for wf, job, step in _steps():
        run = step.get("run", "")
        for cmd in re.findall(r"pip install[^\n]*-r[^\n]*", run):
            assert "--require-hashes" in cmd, f"{wf}/{job}: {cmd}"
            files = re.findall(r"-r\s+(\S+)", cmd)
            assert files and all(f.endswith(".lock") for f in files), f"{wf}/{job}: install from a lock: {cmd}"


def test_the_api_image_installs_its_hashed_lock():
    text = _text(ROOT / "container/api.Dockerfile")
    assert re.search(r"pip install --require-hashes .*-r api/requirements\.lock", text)
    assert "requirements.txt" not in text


def test_the_streamlit_image_installs_its_hashed_lock():
    text = _text(ROOT / "container/streamlit.Dockerfile")
    assert "COPY streamlit_app/requirements.lock" in text
    assert re.search(r"pip install --require-hashes .*-r requirements\.lock", text)
    assert "requirements.txt" not in text


def test_the_offline_bundle_downloads_and_installs_only_hashed_locks():
    build = _text(ROOT / "scripts/offline/build_bundle.sh")
    install = _text(ROOT / "scripts/offline/install.sh")
    for text in (build, install):
        assert not re.search(r"-r \S*requirements\.txt", text), "the offline bundle must use the locks"
    assert "--require-hashes" in build and install.count("--require-hashes") >= 2


# ── #327: JS lock, image digests, healthchecks ────────────────────────────────

def test_the_frontend_has_one_lock_file():
    fe = ROOT / "csv-table-hub-main"
    present = [n for n in ("package-lock.json", "bun.lock", "bun.lockb", "yarn.lock", "pnpm-lock.yaml")
               if (fe / n).exists()]
    assert present == ["package-lock.json"], present


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_base_image_is_pinned_by_digest(path):
    froms = [ins for ins in _text(path).splitlines() if re.match(r"FROM\s", ins)]
    assert froms
    for ins in froms:
        assert re.match(r"FROM\s+\S+:\S+@sha256:[0-9a-f]{64}(\s|$)", ins), f"{path.name}: {ins}"


def test_every_ci_service_and_tool_image_is_pinned_by_digest():
    offenders = []
    for path in WORKFLOWS:
        wf = _workflow(path)
        for job_id, job in wf["jobs"].items():
            for name, svc in (job.get("services") or {}).items():
                if not re.search(r"@sha256:[0-9a-f]{64}$", svc["image"]):
                    offenders.append(f"{path.name}/{job_id}/{name}: {svc['image']}")
        for image in re.findall(r"ghcr\.io/\S+", _text(path)):
            if not re.search(r"@sha256:[0-9a-f]{64}$", image):
                offenders.append(f"{path.name}: {image}")
    assert not offenders, offenders


@pytest.mark.parametrize("image", ["api.Dockerfile", "frontend.Dockerfile"])
def test_the_api_and_frontend_images_have_the_compose_healthcheck(image):
    text = _text(ROOT / "container" / image)
    m = re.search(r"^HEALTHCHECK .*?\\\n\s+CMD (.+)$", text, re.M)
    assert m, f"{image}: no HEALTHCHECK"
    service = {"api.Dockerfile": "api", "frontend.Dockerfile": "frontend"}[image]
    compose = yaml.safe_load(_text(ROOT / "container/docker-compose.yml"))["services"][service]["healthcheck"]
    probe = m.group(1).strip()
    assert compose["test"][0] == "CMD-SHELL"
    # The compose command and the image's are the same probe (quoting aside).
    norm = lambda s: re.sub(r"[\"'\s]", "", s)  # noqa: E731
    assert norm(probe) == norm(compose["test"][1]), (probe, compose["test"][1])


# ── #329 ──────────────────────────────────────────────────────────────────────

def test_a_ci_job_lints_type_checks_and_builds_the_frontend():
    job = _workflow(ROOT / ".github/workflows/quality-gate.yml")["jobs"]["frontend"]
    assert job["defaults"]["run"]["working-directory"] == "csv-table-hub-main"
    runs = [s.get("run", "") for s in job["steps"]]
    for needed in ("npm ci", "npm run lint", "tsc --noEmit", "npm run build", "git status --porcelain"):
        assert any(needed in r for r in runs), f"the frontend job does not run {needed!r}"
    for r in runs:
        assert "|| true" not in r and "continue-on-error" not in str(job), "a failure must fail the job"
