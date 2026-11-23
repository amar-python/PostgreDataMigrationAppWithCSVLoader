"""#326 (SE-05), part 2: what the first image scan found, fixed, and pinned so it does not quietly come back.

The first CI scan of the three images (trivy, HIGH and CRITICAL with a fix) reported, on both CPUs:

  * te-api: zlib1g (Debian security update available);
  * te-db: zlib1g and four Kerberos libraries (Debian security updates available), plus the Go standard library
    inside /usr/local/bin/gosu: 26 findings (1 CRITICAL, 25 HIGH) because the official image's gosu was built with
    Go 1.24.6. The fixes need Go 1.26.10 or newer (1.27.3 or newer on the 1.27 line); the 1.24 and 1.25 lines have no
    fix for some of them. So gosu is rebuilt in db.Dockerfile, with a Go release that has them;
  * te-frontend: ten findings, all inside npm's own bundled packages under /usr/local/lib/node_modules/npm.

The frontend server is started with `node` alone (container/frontend-entrypoint.sh), so npm is not needed in the
image that ships. The Debian findings have a fixed version in Debian's security archive, so the images take it.
No exception for gosu is added to .trivyignore.yaml: the finding is fixed, not accepted.

These read the Dockerfiles as text: the scan itself, in CI, is what proves the findings are gone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]


def dockerfile(name: str) -> str:
    return (ROOT / "container" / name).read_text(encoding="utf-8")


def joined(text: str) -> list[str]:
    """One string per instruction: a backslash at the end of a line continues it."""
    out, current = [], ""
    for raw in text.splitlines():
        if raw.lstrip().startswith("#") and not current:
            continue
        line = raw.rstrip()
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        current += line
        if current.strip():
            out.append(re.sub(r"\s+", " ", current).strip())
        current = ""
    return out


def stages(text: str) -> list[list[str]]:
    result: list[list[str]] = []
    for ins in joined(text):
        if ins.upper().startswith("FROM "):
            result.append([])
        if result:
            result[-1].append(ins)
    return result


def index_of(items: list[str], needle: str) -> int:
    for i, ins in enumerate(items):
        if needle in ins:
            return i
    return -1


def test_the_frontend_image_that_ships_has_no_npm():
    runtime = stages(dockerfile("frontend.Dockerfile"))[-1]
    removal = index_of(runtime, "/usr/local/lib/node_modules/npm")
    assert removal != -1, "the runtime stage must remove npm: its bundled packages carry the scan findings"
    assert runtime[removal].upper().startswith("RUN ") and "rm " in runtime[removal]
    assert "/usr/local/bin/npm" in runtime[removal] and "/usr/local/bin/npx" in runtime[removal], \
        "remove the npm and npx commands too, not just the library folder"
    user = index_of(runtime, "USER node")
    assert user != -1 and removal < user, "removing files needs root: it must come before USER node"


def test_the_frontend_build_stage_keeps_npm():
    build = stages(dockerfile("frontend.Dockerfile"))[0]
    assert index_of(build, "npm ci") != -1 and index_of(build, "npm run build") != -1
    assert index_of(build, "node_modules/npm") == -1, "the build stage needs npm; only the shipped image drops it"


def test_nothing_in_the_container_start_up_needs_npm():
    entrypoint = dockerfile("frontend-entrypoint.sh")
    code = "\n".join(ln for ln in entrypoint.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"\b(npm|npx|yarn|corepack)\b", code), "the server must start with node alone"
    assert "exec node " in code


@pytest.mark.parametrize("image, packages", [
    ("api.Dockerfile", ["zlib1g"]),
    ("db.Dockerfile", ["zlib1g", "libgssapi-krb5-2", "libkrb5-3", "libk5crypto3", "libkrb5support0"]),
])
def test_the_debian_packages_the_scan_flagged_are_upgraded(image, packages):
    items = joined(dockerfile(image))
    upgrade = [ins for ins in items if ins.upper().startswith("RUN ") and "--only-upgrade" in ins]
    assert len(upgrade) == 1, f"{image}: one RUN should take the security updates"
    command = upgrade[0]
    for package in packages:
        assert re.search(rf"(?<![\w.+-]){re.escape(package)}(?![\w.+-])", command), f"{image}: {package} not upgraded"
    assert "apt-get update" in command, "the base image keeps no package lists"
    assert "rm -rf /var/lib/apt/lists/*" in command, "do not leave the package lists in the image"
    assert "apt-get upgrade" not in command and "dist-upgrade" not in command, \
        "upgrade the named packages only: a blanket upgrade could move PostgreSQL or Python itself"


def test_the_api_upgrade_runs_as_root_before_the_app_user():
    items = joined(dockerfile("api.Dockerfile"))
    upgrade = index_of(items, "--only-upgrade")
    user = index_of(items, "USER app")
    assert upgrade != -1 and user != -1 and upgrade < user


# ---- gosu, rebuilt with a Go release that has the standard-library fixes ----------------------------------------

# The oldest Go release that clears all 26 findings in the first scan of the official image's gosu (Go 1.24.6):
# the vulnerability data lists 1.26.10 (and 1.27.3) as the last fix. Raising it is fine; lowering it is not.
GO_MINIMUM = (1, 26, 10)


def db_stages() -> list[list[str]]:
    return stages(dockerfile("db.Dockerfile"))


def test_gosu_is_built_in_its_own_stage_from_a_go_image_that_has_the_fixes():
    stage_list = db_stages()
    assert len(stage_list) == 2, "db.Dockerfile: one stage that builds gosu, then the PostgreSQL image"
    build = stage_list[0]
    assert re.fullmatch(r"FROM golang:1\.\d+ AS gosu", build[0]), "build gosu from a pinned golang release line"
    arg = next((ins for ins in build if ins.startswith("ARG GO_MINIMUM_VERSION=")), None)
    assert arg, "the stage must state the oldest Go release it accepts"
    minimum = tuple(int(part) for part in arg.split("=", 1)[1].split("."))
    assert minimum >= GO_MINIMUM, f"Go {minimum} still has the standard-library findings; need {GO_MINIMUM} or newer"


def test_the_gosu_build_refuses_a_go_older_than_the_minimum():
    run = next(ins for ins in db_stages()[0] if ins.upper().startswith("RUN ") and "go build" in ins)
    assert "GO_MINIMUM_VERSION" in run and "sort -V -C" in run, "compare the image's Go version with the minimum"
    assert re.search(r"\bexit 1\b", run), "an older Go must fail the build, not ship a vulnerable binary quietly"
    version_check = run.index("sort -V -C")
    assert version_check < run.index("go build"), "check the version before building"


def test_gosu_is_built_static_from_a_release_tag_with_the_toolchain_pinned():
    build = db_stages()[0]
    text = " ".join(build)
    assert "ENV GOTOOLCHAIN=local" in build, "Go must not download a different toolchain behind the version check"
    assert "CGO_ENABLED=0" in text, "static binary: it runs in the PostgreSQL image, not the build image"
    assert "-trimpath" in text
    assert "https://github.com/tianon/gosu" in text
    assert re.search(r"ARG GOSU_VERSION=\d+\.\d+\b", text), "build a released gosu, named in one place"
    assert re.search(r'--branch "\$GOSU_VERSION"', text), "check out that release tag, not a moving branch"


def test_the_database_image_runs_the_rebuilt_gosu_at_the_path_the_official_entrypoint_uses():
    final = db_stages()[-1]
    assert final[0] == "FROM postgres:16"
    copy = index_of(final, "COPY --from=gosu")
    assert copy != -1, "copy the rebuilt gosu out of the build stage"
    assert final[copy].rstrip().endswith("/usr/local/bin/gosu"), "docker-entrypoint.sh calls gosu from the PATH"
    check = index_of(final, "gosu nobody true")
    assert check > copy, "run it once in the image, as the official image does, so a broken binary fails the build"
    assert "gosu --version" in final[check]


def test_no_exception_hides_the_gosu_findings():
    ignore = (ROOT / ".trivyignore.yaml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in ignore.splitlines() if not ln.lstrip().startswith("#"))
    assert "gosu" not in code and "CVE-2025-68121" not in code, "fix the finding; do not accept it"
