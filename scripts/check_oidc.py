#!/usr/bin/env python3
"""Check OIDC sign-in against the deployment's real identity provider (#113, BR-36).

Run with the same OIDC_* variables the API reads, and a real ID token for a user who is a member of a tenant:

    export OIDC_ISSUER=https://idp.example.org/realms/te OIDC_AUDIENCE=te-migration \
           OIDC_JWKS_URL=https://idp.example.org/realms/te/protocol/openid-connect/certs
    export ID_TOKEN=...                       # or --token-file PATH, or --token-stdin
    python scripts/check_oidc.py [--api http://localhost:8000 --tenant acme]

It runs the checks one at a time, so a failure names its cause: config, discovery, the key set fetched
over https (the path no automated test could run against a real IdP), the token's signature and claims,
and, with --api, the sign-in itself (POST /api/auth/oidc) and the role it returns. The token is never
accepted on the command line (it would sit in shell history) and neither it nor the session token is
printed. Exit status 0 means every check that ran passed. See docs/OIDC_REAL_IDP_CHECK.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jwt  # noqa: E402

from api import oidc  # noqa: E402
from api.config import settings  # noqa: E402

TIMEOUT = 10


@dataclass
class Result:
    step: str
    status: str        # "ok", "warn" (worth a look, doesn't fail the run) or "fail"
    detail: str


def _open(request):
    """Open a request with a fresh opener. urlopen() keeps one process-wide opener whose TLS trust is fixed the first
    time it is used, so it can't see SSL_CERT_FILE change in the same process."""
    return urllib.request.build_opener().open(request, timeout=TIMEOUT)  # nosec B310 — URLs from the operator's own config


def _get_json(url: str) -> dict:
    with _open(url) as res:
        return json.loads(res.read().decode("utf-8"))


def check_config() -> Result:
    if not settings.OIDC_ISSUER:
        return Result("config", "fail", "OIDC_ISSUER is not set")
    try:
        oidc.check_config()
    except RuntimeError as exc:
        return Result("config", "fail", str(exc))
    if not settings.OIDC_JWKS_URL.startswith("https://"):
        return Result("config", "warn", "OIDC_JWKS_URL is not https://, so the https key fetch isn't being checked")
    return Result("config", "ok", f"issuer {settings.OIDC_ISSUER}, audience {settings.OIDC_AUDIENCE}, "
                                  f"keys {settings.OIDC_JWKS_URL}, username claim {settings.OIDC_USERNAME_CLAIM!r}")


def check_discovery() -> Result:
    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    try:
        doc = _get_json(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Result("discovery", "warn", f"could not read {url}: {exc}. Not required; the other checks still run")
    problems = []
    if doc.get("issuer") != settings.OIDC_ISSUER:
        problems.append(f"the IdP says its issuer is {doc.get('issuer')!r}, but OIDC_ISSUER is {settings.OIDC_ISSUER!r}"
                        " (a trailing slash or the wrong tenant id are the usual causes)")
    if doc.get("jwks_uri") != settings.OIDC_JWKS_URL:
        problems.append(f"the IdP publishes its keys at {doc.get('jwks_uri')!r}, not OIDC_JWKS_URL {settings.OIDC_JWKS_URL!r}")
    return Result("discovery", "warn" if problems else "ok", "; ".join(problems) or "issuer and key URL match what the IdP publishes")


def check_keys() -> Result:
    try:
        source = oidc._jwks(settings.OIDC_JWKS_URL)
        keys = source.get_signing_keys() if isinstance(source, jwt.PyJWKClient) else list(source.keys)
    except Exception as exc:  # noqa: BLE001 — any failure here is what the operator needs to see
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(exc) or "SSL" in str(exc):
            hint = (" The host doesn't trust the IdP's certificate. For a private CA, point SSL_CERT_FILE at the CA bundle "
                    "(PEM) in the API's environment.")
        return Result("keys", "fail", f"{type(exc).__name__}: {exc}.{hint}")
    summary = ", ".join(f"{k.key_id or '(no kid)'} [{k.key_type}]" for k in keys)
    return Result("keys", "ok" if keys else "fail", f"{len(keys)} signing key(s): {summary}" if keys else "the key set is empty")


_HINTS = {
    "InvalidAudienceError": "OIDC_AUDIENCE must be this app's client id, and the token's `aud` must contain it",
    "InvalidIssuerError": "the token's `iss` must equal OIDC_ISSUER exactly",
    "ExpiredSignatureError": "the token has expired; get a fresh one (IdP tokens are short-lived)",
    "ImmatureSignatureError": "the token isn't valid yet: check the clocks of this host and the IdP",
    "MissingRequiredClaimError": "the token lacks a required claim (exp, iat, iss, aud)",
    "InvalidSignatureError": "the signature doesn't match the key the IdP publishes for this key id",
    "PyJWKClientError": "the token's key id isn't in the IdP's key set. A freshly rotated key can be refused for up to 30 seconds",
    "DecodeError": "this isn't a well-formed ID token (an access token or a truncated paste?)",
}


def check_token(token: str) -> Result:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        return Result("token", "fail", f"{type(exc).__name__}: {exc}. {_HINTS['DecodeError']}")
    username_claim = settings.OIDC_USERNAME_CLAIM
    shown = (f"alg {header.get('alg')}, kid {header.get('kid')}, iss {claims.get('iss')}, aud {claims.get('aud')}, "
             f"expires in {int(claims.get('exp', 0) - time.time())} s, {username_claim} = {claims.get(username_claim)!r}")
    try:
        verified = oidc.verify(token)
    except jwt.PyJWTError as exc:
        return Result("token", "fail", f"{shown}. Rejected: {type(exc).__name__}: {exc}. {_HINTS.get(type(exc).__name__, '')}".rstrip())
    username = verified.get(username_claim)
    if not isinstance(username, str) or not username:
        return Result("token", "fail", f"{shown}. Valid, but it has no {username_claim!r} claim, so no user can be named. "
                                       "Set OIDC_USERNAME_CLAIM to the claim that holds the username "
                                       "(Entra ID: preferred_username, or upn in v1 tokens)")
    return Result("token", "ok", f"{shown}. Signature, issuer, audience and expiry verified")


def check_api(api_url: str, tenant: str, token: str) -> Result:
    url = api_url.rstrip("/") + "/api/auth/oidc"
    request = urllib.request.Request(url, data=json.dumps({"tenant": tenant, "idToken": token}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _open(request) as res:
            session = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = {401: "the token verified here but the API refused it, or that user isn't a member of the tenant",
                404: "the API has OIDC switched off: it needs OIDC_ISSUER set in its own environment"}.get(exc.code, "")
        return Result("sign-in", "fail", f"POST {url} gave {exc.code}. {hint}".rstrip())
    except (urllib.error.URLError, OSError) as exc:
        return Result("sign-in", "fail", f"could not reach {url}: {exc}")
    return Result("sign-in", "ok", f"200: signed in as {session.get('username')!r} to tenant {session.get('tenant')!r} "
                                   f"with role {session.get('role')!r}; session expires {session.get('expiresAt')}")


def run_checks(token: str, api_url: str | None = None, tenant: str | None = None, discovery: bool = True) -> list[Result]:
    results = [check_config()]
    if results[0].status == "fail":
        return results
    if discovery:
        results.append(check_discovery())
    results.append(check_keys())
    results.append(check_token(token))
    if api_url and tenant:
        results.append(check_api(api_url, tenant, token))
    return results


def read_token(args) -> str:
    if args.token_stdin:
        return sys.stdin.read().strip()
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    return os.environ.get(args.token_env, "").strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--token-env", default="ID_TOKEN", help="environment variable holding the ID token (default ID_TOKEN)")
    ap.add_argument("--token-file", help="a file holding the ID token")
    ap.add_argument("--token-stdin", action="store_true", help="read the ID token from standard input")
    ap.add_argument("--api", help="also sign in through a running API, e.g. http://localhost:8000")
    ap.add_argument("--tenant", help="the tenant slug to sign in to (with --api)")
    ap.add_argument("--no-discovery", action="store_true", help="skip reading the IdP's discovery document")
    args = ap.parse_args(argv)
    if bool(args.api) != bool(args.tenant):
        ap.error("--api and --tenant go together")
    token = read_token(args)
    if not token:
        print(f"No ID token: set {args.token_env}, or use --token-file or --token-stdin.", file=sys.stderr)
        return 2
    results = run_checks(token, args.api, args.tenant, discovery=not args.no_discovery)
    width = max(len(r.step) for r in results)
    for r in results:
        print(f"{r.status.upper():<5} {r.step:<{width}}  {r.detail}")
    failed = [r.step for r in results if r.status == "fail"]
    ran_api = any(r.step == "sign-in" for r in results)
    print("\nFAILED: " + ", ".join(failed) if failed else
          "\nOK: " + ("sign-in works end to end." if ran_api else
                      "the token verifies. Add --api and --tenant to check the sign-in itself."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
