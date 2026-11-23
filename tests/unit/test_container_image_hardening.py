"""#326 (SE-05), part 2: what the first image scan found, fixed, and pinned so it does not quietly come back.

The first CI scan of the three images (trivy, HIGH and CRITICAL with a fix) reported, on both CPUs:

  * te-api: zlib1g (Debian security update available);
  * te-db: zlib1g and four Kerberos libraries (Debian security updates available), plus the Go standard library
    inside /usr/local/bin/gosu (not fixable here: it needs a rebuilt gosu, see .trivyignore.yaml and the PR);
  * te-frontend: ten findings, all inside npm's own bundled packages under /usr/local/lib/node_modules/npm.

The frontend server is started with `node` alone (container/frontend-entrypoint.sh), so npm is not needed in the
image that ships. The Debian findings have a fixed version in Debian's security archive, so the images take it.

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
