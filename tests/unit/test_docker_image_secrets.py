"""RV-S4 (#174): the migration image must not be able to bake local credentials.

`build/config.local.env` (written by build/setup.sh and
scripts/provision_full_test_env.sh) and the concrete
`build/environments/env_<env>.sql` files (generated from the committed
`.example.sql` templates) both hold real credentials. They are gitignored, but
.gitignore does not filter the Docker build context, so `docker build .` from a
configured checkout could copy them into an image layer. Layers are immutable
and cached indefinitely: once pushed to a registry, rotating the leaked
password is the only remediation.

Two independent layers stop that, and this module tests both:

  (a) .dockerignore excludes the files, so they are not in the build context.
  (b) infra/Dockerfile names an explicit source list, so nothing under build/
      reaches the image unless a COPY asks for it by name.

No Docker daemon is needed. Issue #174 allows this static equivalent of the
`docker save` + `grep` check: it compares the Dockerfile's build-context file
list before and after the fix, which is what the daemon-based check would
observe. On `main` at c7bebd1 the Dockerfile had a single
`COPY build/ ./build/`, so TestExplicitCopyList fails there.
"""
from __future__ import annotations

import fnmatch
import re
import unittest
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "infra" / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"

# Credential-bearing paths, relative to the build context (the repo root).
# These are the files RV-S4 found reachable; every one is gitignored, so a clean
# CI checkout does not have them and the test synthesises them instead.
SENSITIVE = (
    "build/config.local.env",
    "build/config.local.env.new",  # written by the RV-S2 fix
    "build/environments/env_dev.sql",
    "build/environments/env_test.sql",
    "build/environments/env_staging.sql",
    "build/environments/env_prod.sql",
)

# The committed templates carry no secrets and the image needs them, so a
# pattern that swept these up alongside the files above would be wrong.
TEMPLATES = (
    "build/environments/env_dev.example.sql",
    "build/environments/env_prod.example.sql",
)

_COPY = re.compile(r"^\s*COPY\s+(?P<rest>.+?)\s*$", re.IGNORECASE)
_FLAG = re.compile(r"^--\S+$")


def copy_sources() -> list[str]:
    """Every source path pattern named by a COPY in infra/Dockerfile.

    The last token of a COPY is the destination; `--chown=` and friends are
    dropped. Line continuations are not used in this Dockerfile; if one is
    added, the assertion in TestDockerfileParses catches the parser going blind.
    """
    sources: list[str] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        m = _COPY.match(line)
        if not m:
            continue
        tokens = [t for t in m.group("rest").split() if not _FLAG.match(t)]
        sources.extend(tokens[:-1])  # drop the destination
    return sources


def expand(source: str) -> set[str]:
    """Context-relative files a single COPY source brings in, as Docker would.

    A trailing `/` copies a directory tree; anything else is a glob over files.
    """
    if source.endswith("/"):
        base = ROOT / source
        return {
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in base.rglob("*")
            if p.is_file()
        }
    return {
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in ROOT.glob(source)
        if p.is_file()
    }


def ignore_patterns() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def is_ignored(path: str) -> bool:
    """Whether .dockerignore excludes `path`, last matching pattern winning.

    Docker's own matcher is more general than this (it understands `**` at any
    position); this covers the shapes the file actually uses — an exact path, a
    basename glob, and a `**/`-prefixed glob — and errs towards reporting a file
    as NOT ignored, so it cannot mask a leak.
    """
    ignored = False
    for pattern in ignore_patterns():
        negated = pattern.startswith("!")
        pat = pattern.lstrip("!")
        if pat.startswith("**/"):
            hit = fnmatch.fnmatch(Path(path).name, pat[3:])
        elif "/" in pat:
            hit = fnmatch.fnmatch(path, pat)
        else:
            hit = fnmatch.fnmatch(Path(path).name, pat)
        if hit:
            ignored = not negated
    return ignored


class TestDockerfileParses(unittest.TestCase):
    """Guard the parser the other tests rely on."""

    def test_copy_lines_were_found(self):
        self.assertGreater(len(copy_sources()), 1, "parsed no COPY sources from infra/Dockerfile")

    def test_no_line_continuations_in_copy(self):
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
            if _COPY.match(line):
                self.assertFalse(
                    line.rstrip().endswith("\\"),
                    f"COPY uses a line continuation, which copy_sources() cannot read:\n  {line}",
                )


class TestExplicitCopyList(unittest.TestCase):
    """Layer (b): no COPY in the Dockerfile may name a credential-bearing file.

    Synthetic secrets stand in for a configured checkout, as #174's verification
    step describes. They are gitignored, so creating them is safe, and cleanup
    removes them.
    """

    def setUp(self):
        for rel in SENSITIVE:
            path = ROOT / rel
            if path.exists():
                continue  # a real configured checkout; leave the developer's file alone
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("PGPASSWORD=synthetic-rvs4-secret\n", encoding="utf-8")
            self.addCleanup(path.unlink)

    def test_no_copy_source_matches_a_sensitive_file(self):
        copied: set[str] = set()
        for source in copy_sources():
            copied |= expand(source)
        leaked = sorted(set(SENSITIVE) & copied)
        self.assertEqual(
            leaked,
            [],
            "infra/Dockerfile copies credential-bearing files into the image: "
            f"{leaked}. Name the files the image needs individually instead of "
            "copying a directory wholesale (RV-S4, #174).",
        )

    def test_templates_are_still_copied(self):
        """The fix must not cost the image the files it needs to run."""
        copied: set[str] = set()
        for source in copy_sources():
            copied |= expand(source)
        for template in TEMPLATES:
            self.assertIn(
                template,
                copied,
                f"{template} is no longer copied into the image; deploy_all.sh needs it.",
            )
        self.assertIn("build/deploy_all.sh", copied, "the entrypoint runs build/deploy_all.sh")
        self.assertIn("build/te_core_schema.sql", copied, "env_*.sql includes te_core_schema.sql")


class TestDockerignoreExcludesSecrets(unittest.TestCase):
    """Layer (a): the files are kept out of the build context as well."""

    def test_sensitive_files_are_ignored(self):
        missed = [rel for rel in SENSITIVE if not is_ignored(rel)]
        self.assertEqual(
            missed,
            [],
            f".dockerignore does not exclude {missed}. .gitignore has no effect on "
            "the Docker build context, so each must be listed in .dockerignore too "
            "(RV-S4, #174).",
        )

    def test_templates_are_not_ignored(self):
        kept = [rel for rel in TEMPLATES if is_ignored(rel)]
        self.assertEqual(
            kept,
            [],
            f".dockerignore excludes the committed templates {kept}, which the image needs.",
        )


if __name__ == "__main__":
    unittest.main()
