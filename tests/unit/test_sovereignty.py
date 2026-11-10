"""No runtime external services in what we ship (M7, #111; BR-37, decision 7). No database, no network.

Static checks over the API and the frontend source. They don't replace running the suite with egress
blocked (`pytest --block-egress`), which catches what the code does rather than what it says.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_HOST = re.compile(r"https?://([A-Za-z0-9._-]+)", re.I)
_LOCAL = {"localhost", "127.0.0.1"}
# The one external host a frontend source file may name: an XML namespace identifier, never fetched.
_FRONTEND_ALLOWED = _LOCAL | {"www.w3.org"}
# Modules that make outbound requests. The API imports none. Its one external call, the OIDC key fetch,
# is made by PyJWT and only when OIDC_ISSUER is set, to an IdP the deployment controls (api/oidc.py).
_HTTP_MODULES = {"requests", "httpx", "aiohttp", "urllib3", "urllib.request", "http.client", "ftplib", "smtplib",
                 "telnetlib", "xmlrpc.client", "websockets", "boto3", "botocore"}
# urllib.request names that only convert between paths and URLs.
_URL_PATH_HELPERS = {"url2pathname", "pathname2url"}
# npm packages that phone home to a third party.
_TELEMETRY = ("sentry", "posthog", "mixpanel", "segment", "amplitude", "datadog", "newrelic", "hotjar", "logrocket",
              "fullstory", "bugsnag", "rollbar", "analytics", "gtag", "heap", "intercom")


def _hosts(path: Path) -> set[str]:
    return {h.lower().rstrip(".") for h in _HOST.findall(path.read_text(encoding="utf-8", errors="ignore"))}


def _frontend_sources() -> list[Path]:
    src = _ROOT / "csv-table-hub-main" / "src"
    files = [p for p in src.rglob("*") if p.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".svg", ".json"}
             and "__tests__" not in p.parts]
    public = _ROOT / "csv-table-hub-main" / "public"
    return files + (list(public.rglob("*")) if public.exists() else [])


@pytest.mark.unit
class ApiMakesNoOutboundCalls(unittest.TestCase):
    def test_the_api_imports_no_http_client(self):
        found = []
        for path in (_ROOT / "api").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module == "urllib.request" and \
                        {a.name for a in node.names} <= _URL_PATH_HELPERS:
                    continue   # url2pathname turns a file:// URL into a path; it opens nothing
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                found += [f"{path.relative_to(_ROOT)}: {n}" for n in names
                          if n in _HTTP_MODULES or n.split(".")[0] in _HTTP_MODULES]
        self.assertEqual(found, [])

    def test_the_scan_catches_a_network_capable_urllib_import(self):
        node = ast.parse("from urllib.request import urlopen").body[0]
        self.assertFalse({a.name for a in node.names} <= _URL_PATH_HELPERS)

    def test_the_api_names_no_external_host(self):
        found = {str(p.relative_to(_ROOT)): sorted(_hosts(p) - _LOCAL) for p in (_ROOT / "api").rglob("*.py")}
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_oidc_only_accepts_https_or_file_key_urls(self):
        text = (_ROOT / "api" / "oidc.py").read_text(encoding="utf-8")
        self.assertIn('startswith(("https://", "file://"))', text)


@pytest.mark.unit
class FrontendReachesNoThirdParty(unittest.TestCase):
    def test_no_source_file_names_an_external_host(self):
        found = {str(p.relative_to(_ROOT)): sorted(_hosts(p) - _FRONTEND_ALLOWED) for p in _frontend_sources()}
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_no_telemetry_package_is_a_dependency(self):
        manifest = json.loads((_ROOT / "csv-table-hub-main" / "package.json").read_text(encoding="utf-8"))
        names = [*manifest.get("dependencies", {}), *manifest.get("devDependencies", {})]
        self.assertEqual([n for n in names if any(t in n.lower() for t in _TELEMETRY)], [])

    def test_no_html_entry_loads_a_remote_script_or_stylesheet(self):
        offenders = []
        for page in (_ROOT / "csv-table-hub-main").rglob("*.html"):
            if "node_modules" in page.parts or "dist" in page.parts:
                continue
            offenders += re.findall(r"""(?:src|href)\s*=\s*["']((?:https?:)?//[^"']+)""", page.read_text(errors="ignore"))
        self.assertEqual(offenders, [])

    def test_the_scan_would_catch_a_cdn(self):
        # The check isn't vacuous: it flags the hosts a real violation would use.
        sample = 'import "https://cdn.jsdelivr.net/npm/x"; fetch("https://www.google-analytics.com/collect")'
        self.assertEqual({h.lower() for h in _HOST.findall(sample)} - _FRONTEND_ALLOWED,
                         {"cdn.jsdelivr.net", "www.google-analytics.com"})


def _checker():
    spec = importlib.util.spec_from_file_location("check_bundle_egress", _ROOT / "scripts" / "check_bundle_egress.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class BundleChecker(unittest.TestCase):
    """scripts/check_bundle_egress.py fails on what a real violation looks like and ignores namespace names."""

    def scan(self, files: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            return _checker().scan(Path(tmp))

    def test_namespaces_documentation_links_and_new_url_are_not_load_paths(self):
        found = self.scan({"app.js": 'const ns = "http://www.w3.org/2000/svg"; new URL("https://exa\\nmple.com");'
                                     ' // https://react.dev/errors/418', "a.css": "a { color: red }"})
        self.assertEqual((found["loads"], found["banned"]), ([], []))
        self.assertIn("www.w3.org", found["other"])

    def test_external_markup_resources_are_load_paths(self):
        for name, text in (("index.html", '<script src="https://cdn.example.org/x.js"></script>'),
                           ("index.html", '<link rel="stylesheet" href="//fonts.example.org/f.css">'),
                           ("a.css", '@import url("https://fonts.example.org/f.css");'),
                           ("a.css", "a { background: url(https://img.example.org/b.png) }")):
            self.assertEqual(len(self.scan({name: text})["loads"]), 1, text)

    def test_literal_external_requests_in_scripts_are_load_paths(self):
        for text in ('fetch("https://api.example.org/x")', 'x.open("GET", "https://api.example.org/x")',
                     'navigator.sendBeacon("https://t.example.org/c")', 'new WebSocket("wss://ws.example.org")',
                     'import("https://esm.example.org/m.js")'):
            self.assertEqual(len(self.scan({"app.js": text})["loads"]), 1, text)

    def test_requests_to_this_machine_are_fine(self):
        self.assertEqual(self.scan({"app.js": 'fetch("http://localhost:8000/api/x")'})["loads"], [])

    def test_analytics_and_cdn_hosts_fail_wherever_they_appear(self):
        found = self.scan({"app.js": 'const a = "https://www.google-analytics.com/collect"; // https://cdn.jsdelivr.net/x'})
        self.assertEqual(sorted(h.split(": ")[1] for h in found["banned"]),
                         ["cdn.jsdelivr.net", "www.google-analytics.com"])
