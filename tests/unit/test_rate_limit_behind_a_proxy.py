"""#293 (OIT-008, SECURITY_REVIEW_PACK F3): the rate limit behind a reverse proxy.

``api/ratelimit.py`` keys the limit on ``request.client.host``, the peer address, and its docstring said it
"deliberately ignores" ``X-Forwarded-For`` so a client cannot mint buckets by varying the header. Behind a reverse proxy
every caller then shares the proxy's address, so one client could use up everyone's budget. The remedy was thought to
need new code. It does not: uvicorn already wraps the app in ``ProxyHeadersMiddleware``, which, only for peers listed in
``FORWARDED_ALLOW_IPS`` (default ``127.0.0.1,::1``), replaces the client address with the right-most address in
``X-Forwarded-For`` that is not itself a trusted proxy. The limiter therefore already sees the real client behind a
trusted proxy, and the peer everywhere else. Asserted here, through the wrapper uvicorn itself builds
(``uvicorn.Config(...).load()``), with the environment variable an operator would set:

  * two clients behind a trusted proxy have separate budgets (the issue's acceptance test), and one of them is still
    limited;
  * a client that forges the header, by adding its own addresses to the left of the one the proxy appends, gets no new
    budget; and a header from a peer that is not a trusted proxy is ignored, which is the default for every address but
    loopback;
  * nothing in the repo's start-up commands or infrastructure trusts every peer (``*``) or switches proxy headers off;
  * the setting, and the two rate-limit settings that were undocumented, are documented, and so is where a limit set in
    the proxy belongs; the limiter's docstring says how the client address is chosen.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app
from api.ratelimit import _client_id, limiter

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = {"fileName": "x.csv", "content": "a,b\n1,2\n"}
PROXY = "10.0.0.1"


@pytest.fixture(autouse=True)
def small_write_budget(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_WRITES_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "API_KEY", "")
    limiter.reset()
    yield
    limiter.reset()


def served(monkeypatch, forwarded_allow_ips: str | None, peer: str = PROXY) -> TestClient:
    """The app exactly as ``uvicorn`` would serve it with that environment, called from ``peer``."""
    if forwarded_allow_ips is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", forwarded_allow_ips)
    config = uvicorn.Config("api.main:app", log_config=None)
    config.load()
    return TestClient(config.loaded_app, client=(peer, 5000))


def preview(client: TestClient, forwarded: str) -> int:
    return client.post("/api/csv/preview", json=PAYLOAD, headers={"X-Forwarded-For": forwarded}).status_code


# -- behind a trusted proxy ------------------------------------------------------------------------------------------

def test_two_clients_behind_a_trusted_proxy_have_separate_budgets(monkeypatch):
    client = served(monkeypatch, PROXY)
    assert [preview(client, "203.0.113.5") for _ in range(2)] == [200, 200]
    assert preview(client, "203.0.113.5") == 429, "the first client has used its budget"
    assert preview(client, "203.0.113.6") == 200, "a second client behind the same proxy has its own"


def test_a_trusted_proxy_range_works_too(monkeypatch):
    client = served(monkeypatch, "10.0.0.0/24")
    assert [preview(client, "203.0.113.5") for _ in range(2)] == [200, 200]
    assert preview(client, "203.0.113.5") == 429
    assert preview(client, "203.0.113.6") == 200


def test_a_chain_of_trusted_proxies_resolves_to_the_client(monkeypatch):
    """client -> proxy 10.0.0.9 -> proxy 10.0.0.1 (the peer): both trusted, so the client is what is left."""
    client = served(monkeypatch, "10.0.0.1,10.0.0.9")
    assert [preview(client, "203.0.113.5, 10.0.0.9") for _ in range(2)] == [200, 200]
    assert preview(client, "203.0.113.5, 10.0.0.9") == 429
    assert preview(client, "203.0.113.6, 10.0.0.9") == 200


def test_forging_the_header_does_not_mint_a_budget_behind_a_trusted_proxy(monkeypatch):
    """The proxy appends the real client on the right; whatever a client sends on the left is not trusted."""
    client = served(monkeypatch, PROXY)
    statuses = [preview(client, f"{fake}, 203.0.113.5") for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3")]
    assert statuses == [200, 200, 429], statuses


# -- not behind a trusted proxy --------------------------------------------------------------------------------------

def test_a_header_from_an_untrusted_peer_is_ignored(monkeypatch):
    client = served(monkeypatch, "10.0.0.2")             # a different address is the trusted one
    statuses = [preview(client, f"203.0.113.{i}") for i in range(3)]
    assert statuses == [200, 200, 429], "all three share the peer's budget, whatever the header says"


def test_by_default_only_loopback_is_trusted(monkeypatch):
    assert uvicorn.Config("api.main:app", log_config=None).forwarded_allow_ips in ("127.0.0.1,::1", "127.0.0.1")
    client = served(monkeypatch, None)                    # FORWARDED_ALLOW_IPS unset: the shipped default
    assert [preview(client, f"203.0.113.{i}") for i in range(3)] == [200, 200, 429]


def test_a_loopback_proxy_is_trusted_by_default(monkeypatch):
    client = served(monkeypatch, None, peer="127.0.0.1")  # nginx on the same host
    assert [preview(client, "203.0.113.5") for _ in range(2)] == [200, 200]
    assert preview(client, "203.0.113.5") == 429
    assert preview(client, "203.0.113.6") == 200


def test_the_limiter_itself_keys_on_whatever_client_address_it_is_given():
    """Without the wrapper (a different server, or a test), the peer is the identity and the header is not."""
    from starlette.requests import Request
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.5")], "client": (PROXY, 5000)}
    assert _client_id(Request(scope)) == f"ip:{PROXY}"


# -- what the repo starts, and what it says --------------------------------------------------------------------------

def _start_up_files() -> list[Path]:
    roots = [ROOT / "container", ROOT / "scripts" / "offline", ROOT / "infra", ROOT / ".github" / "workflows"]
    found = []
    for base in roots:
        for path in base.rglob("*"):
            scanned = path.suffix in {".sh", ".ps1", ".yml", ".yaml", ".tf", ".tfvars", ".json", ".md", ""} \
                or "dockerfile" in path.name.lower()       # api.Dockerfile has the suffix ".Dockerfile"
            if path.is_file() and ".terraform" not in path.parts and scanned:
                found.append(path)
    assert any(p.name == "api.Dockerfile" for p in found), "the scan must include the API image"
    return found + [p for p in (ROOT / "README.md", ROOT / "env.dev.example") if p.exists()]


def test_nothing_trusts_every_peer_or_turns_proxy_headers_off():
    """``*`` would let any caller set the header and pick its own identity; ``--no-proxy-headers`` undoes this fix."""
    trust_all = re.compile(r"(?i)forwarded[-_]allow[-_]ips\s*[=:]?\s*[\"']?\s*\*")
    for path in _start_up_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not trust_all.search(text), f"{path.relative_to(ROOT)} trusts every peer to set X-Forwarded-For"
        assert "--no-proxy-headers" not in text, f"{path.relative_to(ROOT)} turns proxy headers off"


def _row(name: str) -> str:
    text = (ROOT / "docs" / "ENV_VARIABLES.md").read_text(encoding="utf-8")
    match = re.search(rf"^\| `{name}` \|(.*)$", text, re.MULTILINE)
    assert match, f"docs/ENV_VARIABLES.md must document {name}"
    return match.group(1)


def test_the_settings_are_documented():
    reads, writes, forwarded = _row("API_RATE_LIMIT_READS"), _row("API_RATE_LIMIT_WRITES"), _row("FORWARDED_ALLOW_IPS")
    assert "120" in reads and "0" in reads, reads
    assert "20" in writes and "0" in writes, writes
    for needed in ("X-Forwarded-For", "proxy", "127.0.0.1", "*"):
        assert needed in forwarded, f"the FORWARDED_ALLOW_IPS row should mention {needed!r}: {forwarded}"


def test_the_deployment_guide_says_what_to_do_behind_a_proxy():
    guide = (ROOT / "docs" / "PROD_DEPLOY.md").read_text(encoding="utf-8")
    section = re.search(r"(?ms)^## [^\n]*reverse proxy[^\n]*\n(.*?)(?=^## |\Z)", guide, re.IGNORECASE)
    assert section, "docs/PROD_DEPLOY.md needs a section about running behind a reverse proxy"
    for needed in ("FORWARDED_ALLOW_IPS", "X-Forwarded-For", "per instance", "rate limit"):
        assert needed.lower() in section.group(1).lower(), f"that section should mention {needed!r}"


def test_the_limiters_docstring_says_how_the_client_address_is_chosen():
    doc = _client_id.__doc__ or ""
    assert "FORWARDED_ALLOW_IPS" in doc and "ProxyHeadersMiddleware" in doc, doc
    assert "deliberately ignored" not in doc, "it is ignored from untrusted peers only"
