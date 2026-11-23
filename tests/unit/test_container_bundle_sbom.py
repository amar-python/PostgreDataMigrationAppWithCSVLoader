"""#326 (SE-05), part 2: the container bundle carries an SBOM for every image, and cannot quietly lose them.

A defence customer receiving the offline bundle has no component list to assess or accredit unless the bundle holds
one. CI writes a CycloneDX SBOM per image per CPU (trivy, see container-bundle.yml); `build_bundle.sh assemble` puts
them in the bundle under sbom/, lists them in SHA256SUMS (so the installers verify them with the rest), and with
TE_REQUIRE_SBOM=1 refuses to build a bundle that is missing one, or holds a file that is not an SBOM.

These run the real assemble step on fake tarballs in a scratch copy of container/, so nothing is written to the
repository's dist/. `tooling` only: they need bash, and the Windows job selects unit/regression (on its runner `bash`
is WSL's, with no distribution installed).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ("api", "frontend", "db")
CYCLONEDX = '{\n  "bomFormat": "CycloneDX",\n  "specVersion": "1.6",\n  "components": [{"name": "libc6"}]\n}\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """container/ copied to a scratch root: build_bundle.sh takes its root from its own location."""
    shutil.copytree(ROOT / "container", tmp_path / "container", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "dist").mkdir()
    return tmp_path


def tarball(repo: Path, arch: str) -> str:
    path = repo / "dist" / f"te-images-v1-{arch}.tar"
    path.write_bytes(b"fake images for " + arch.encode())
    return str(path)


def sbom(repo: Path, image: str, arch: str, text: str = CYCLONEDX) -> Path:
    path = repo / "dist" / "sbom" / f"te-{image}-{arch}.cdx.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def all_sboms(repo: Path, *archs: str) -> None:
    for arch in archs:
        for image in IMAGES:
            sbom(repo, image, arch)


def assemble(repo: Path, *tars: str, require: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "TE_VERSION": "v1"}
    env.pop("TE_REQUIRE_SBOM", None)
    if require:
        env["TE_REQUIRE_SBOM"] = "1"
    return subprocess.run(["bash", str(repo / "container" / "build_bundle.sh"), "assemble", *tars], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=120)


def bundle(repo: Path) -> Path:
    return repo / "dist" / "te-container-bundle-v1"


def sbom_names(repo: Path) -> list[str]:
    folder = bundle(repo) / "sbom"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def checksums_verify(folder: Path) -> list[str]:
    """Names listed in SHA256SUMS whose file is missing or whose hash is wrong, as install.sh and install.ps1 check."""
    bad, listed = [], []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        name = name.lstrip("*").strip()
        listed.append(name)
        target = folder / name
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            bad.append(name)
    return bad if listed else ["(SHA256SUMS is empty)"]


def listed(repo: Path) -> list[str]:
    return [line.split(None, 1)[1].lstrip("*").strip()
            for line in (bundle(repo) / "SHA256SUMS").read_text(encoding="utf-8").splitlines()]


def test_a_bundle_with_no_sbom_builds_as_it_always_did(repo):
    result = assemble(repo, tarball(repo, "amd64"))
    assert result.returncode == 0, result.stderr
    assert not (bundle(repo) / "sbom").exists()
    assert checksums_verify(bundle(repo)) == []
    assert {"images-amd64.tar", "docker-compose.yml", "install.sh", "install.ps1", "VERSION"} <= set(listed(repo))


def test_the_sboms_of_the_cpus_in_the_bundle_are_included_and_checksummed(repo):
    all_sboms(repo, "amd64", "arm64")
    result = assemble(repo, tarball(repo, "amd64"), tarball(repo, "arm64"), require=True)
    assert result.returncode == 0, result.stderr
    assert sbom_names(repo) == sorted(f"te-{i}-{a}.cdx.json" for a in ("amd64", "arm64") for i in IMAGES)
    assert checksums_verify(bundle(repo)) == [], "the installers verify SHA256SUMS, so it must cover sbom/ too"
    assert "sbom/te-api-amd64.cdx.json" in listed(repo)


def test_the_bundle_archive_holds_the_sboms(repo):
    all_sboms(repo, "amd64")
    assert assemble(repo, tarball(repo, "amd64"), require=True).returncode == 0
    with tarfile.open(repo / "dist" / "te-container-bundle-v1.tar.gz") as archive:
        names = archive.getnames()
    assert sum(n.endswith(".cdx.json") and "/sbom/" in n for n in names) == 3


def test_an_sbom_for_a_cpu_that_is_not_in_the_bundle_is_left_out(repo):
    all_sboms(repo, "amd64", "arm64")
    assert assemble(repo, tarball(repo, "amd64"), require=True).returncode == 0
    assert sbom_names(repo) == sorted(f"te-{i}-amd64.cdx.json" for i in IMAGES)


def test_a_required_sbom_that_is_missing_fails_the_build_and_names_the_file(repo):
    all_sboms(repo, "amd64", "arm64")
    sbom(repo, "db", "arm64").unlink()
    result = assemble(repo, tarball(repo, "amd64"), tarball(repo, "arm64"), require=True)
    assert result.returncode != 0
    assert "te-db-arm64.cdx.json" in result.stderr
    assert not (repo / "dist" / "te-container-bundle-v1.tar.gz").exists(), "no archive may be made from a bad bundle"


def test_a_required_sbom_that_is_not_cyclonedx_fails_the_build(repo):
    all_sboms(repo, "amd64")
    sbom(repo, "api", "amd64", "this is not an SBOM\n")
    result = assemble(repo, tarball(repo, "amd64"), require=True)
    assert result.returncode != 0 and "te-api-amd64.cdx.json" in result.stderr


def test_a_required_sbom_that_lists_no_components_fails_the_build(repo):
    all_sboms(repo, "amd64")
    sbom(repo, "frontend", "amd64", '{"bomFormat": "CycloneDX", "specVersion": "1.6"}\n')
    result = assemble(repo, tarball(repo, "amd64"), require=True)
    assert result.returncode != 0 and "te-frontend-amd64.cdx.json" in result.stderr


def test_requiring_sboms_when_there_is_no_sbom_directory_fails_the_build(repo):
    result = assemble(repo, tarball(repo, "amd64"), require=True)
    assert result.returncode != 0 and "SBOM" in result.stderr


def test_the_final_message_counts_the_sboms(repo):
    all_sboms(repo, "amd64")
    result = assemble(repo, tarball(repo, "amd64"), require=True)
    assert "SBOMs: 3" in result.stdout, result.stdout
