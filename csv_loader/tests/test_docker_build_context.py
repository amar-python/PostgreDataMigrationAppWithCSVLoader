"""#348 (CLI-02): the csv_loader image must contain the application and nothing else.

The Dockerfile ended with ``COPY . .``. Built from a folder inside a home directory, that copies everything in it into an
image layer: SSH keys, cloud-CLI logins, tool configuration, downloads. Layers are immutable and cached, and one
``docker push`` would publish them. ``.dockerignore`` held only ``.env`` of the credential files.

Two independent layers must each stop that, and this module tests both (same approach as tests/unit/test_docker_image_secrets.py
at the repository root, #174): the Dockerfile names an explicit source list, so nothing reaches the image unless a COPY asks
for it; and ``.dockerignore`` excludes credential files and folders from the build context as a second line of defence.

No Docker daemon is needed. The check computes the files a build would copy: the COPY sources, expanded inside a synthetic
context that holds credential files, minus what ``.dockerignore`` excludes. That is what ``docker run image ls -A`` would
show for the copied layer. (Not run against a real daemon here: none was available.)
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"

# What a home folder holds that must never reach an image.
SENSITIVE = (
    ".env", ".env.local", "config.local.env", ".ssh/id_rsa", ".ssh/known_hosts", ".aws/credentials", ".azure/accessTokens.json",
    ".gnupg/private-keys.gpg", ".kube/config", ".docker/config.json", ".config/gcloud/credentials.db", "server.pem",
    "deploy.key", "id_ed25519", "terraform.tfvars", "terraform.tfstate", ".git/config", "OneDrive/Desktop/notes.txt",
)
# Files that are not credentials but are not the application either (data is mounted at run time, tests are not shipped).
NOT_APPLICATION = ("input_data/users.csv", "reports/run/summary.json", "tests/test_config.py", "Downloads/report.pdf",
                   "auto_migrate.py", "Dockerfile")
APPLICATION = ("requirements.txt", "main.py", "config.yaml", "src/__init__.py", "src/config.py", "src/migrator.py")

_COPY = re.compile(r"^\s*(COPY|ADD)\s+(?P<rest>.+?)\s*$", re.IGNORECASE)


def copy_sources(dockerfile_text: str) -> list[str]:
    """Source paths of every COPY/ADD (the last token is the destination; --flags are dropped)."""
    out: list[str] = []
    for line in dockerfile_text.splitlines():
        m = _COPY.match(line)
        if m:
            tokens = [t for t in m.group("rest").split() if not t.startswith("--")]
            out += tokens[:-1]
    return out


def ignored(rel: str, patterns: list[str]) -> bool:
    """Docker's .dockerignore matching, simplified: a pattern excludes a path, or any folder above it. A pattern with no
    ``**/`` prefix matches from the context root only (so ``*.pem`` does not exclude ``a/b.pem``)."""
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.strip().rstrip("/")
        if not pat or pat.startswith("#"):
            continue
        anywhere = pat.startswith("**/")
        pat = pat[3:] if anywhere else pat
        for k in range(1, len(parts) + 1):
            if anywhere:
                candidates = ["/".join(parts[i:k]) for i in range(0, k)]
            else:
                candidates = ["/".join(parts[:k])]
            if any(fnmatch.fnmatchcase(c, pat) for c in candidates):
                return True
    return False


def context_files(tmp: Path) -> list[str]:
    for rel in SENSITIVE + NOT_APPLICATION + APPLICATION:
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("x", encoding="utf-8")
    return sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file())


def image_files(dockerfile_text: str, dockerignore_text: str, tmp: Path) -> set[str]:
    """The files the COPY lines would put in the image from a build context that contains everything in tmp."""
    files = context_files(tmp)
    patterns = dockerignore_text.splitlines()
    kept = [f for f in files if not ignored(f, patterns)]
    copied: set[str] = set()
    for src in copy_sources(dockerfile_text):
        s = src.strip("./") if src not in (".", "./") else ""
        for f in kept:
            if s == "" or f == s or f.startswith(s.rstrip("/") + "/") or fnmatch.fnmatchcase(f, s):
                copied.add(f)
    return copied


# -- layer (a): the Dockerfile names what it copies ----------------------------------------------------------------------

def test_the_dockerfile_copies_no_whole_folder_from_the_context_root():
    sources = copy_sources(DOCKERFILE.read_text(encoding="utf-8"))
    assert sources, "the parser found no COPY, so this check would pass on nothing"
    whole = [s for s in sources if s.strip() in (".", "./", "*", "./*", "/")]
    assert not whole, f"COPY of the whole build context: {whole} (credentials in the home folder would go into the image)"


def test_the_dockerfile_copies_only_the_application_by_name():
    sources = set(copy_sources(DOCKERFILE.read_text(encoding="utf-8")))
    allowed = {"requirements.txt", "main.py", "config.yaml", "src/"}
    assert sources <= allowed, f"unexpected COPY sources: {sorted(sources - allowed)}"
    assert {"main.py", "config.yaml", "src/", "requirements.txt"} <= sources, "the image would not run without these"
    for src in sources:
        assert (ROOT / src).exists(), f"COPY names {src}, which does not exist"


def test_with_no_dockerignore_at_all_the_image_still_holds_no_credential(tmp_path):
    """Layer (a) alone: the explicit list keeps a credential out even if .dockerignore were deleted."""
    copied = image_files(DOCKERFILE.read_text(encoding="utf-8"), "", tmp_path)
    assert not (copied & set(SENSITIVE)), f"credential files copied into the image: {sorted(copied & set(SENSITIVE))}"


def test_the_image_holds_the_application_and_not_the_data_tests_or_dev_tools(tmp_path):
    copied = image_files(DOCKERFILE.read_text(encoding="utf-8"), DOCKERIGNORE.read_text(encoding="utf-8"), tmp_path)
    assert set(APPLICATION) <= copied, f"missing from the image: {sorted(set(APPLICATION) - copied)}"
    assert not (copied & set(NOT_APPLICATION)), f"not part of the application: {sorted(copied & set(NOT_APPLICATION))}"


# -- layer (b): .dockerignore keeps credentials out of the build context -------------------------------------------------

def test_with_a_copy_everything_dockerfile_the_dockerignore_alone_still_excludes_every_credential(tmp_path):
    """Layer (b) alone: if someone puts back `COPY . .`, the build context still holds no credential."""
    copied = image_files("COPY . .\n", DOCKERIGNORE.read_text(encoding="utf-8"), tmp_path)
    leaked = sorted(copied & set(SENSITIVE))
    assert not leaked, f".dockerignore lets these into the context: {leaked}"


def test_the_dockerignore_names_the_credential_folders():
    text = DOCKERIGNORE.read_text(encoding="utf-8")
    for needed in (".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".git", ".env", "*.pem", "*.key", "*.tfvars",
                   "input_data", "reports"):
        assert needed in text, f".dockerignore does not mention {needed}"


def test_the_checker_itself_sees_a_leak(tmp_path):
    """Control: with neither layer, the same check reports the credentials, so a zero above is not just a blind parser."""
    copied = image_files("COPY . .\n", "", tmp_path)
    assert {".ssh/id_rsa", ".aws/credentials", ".env"} <= copied
