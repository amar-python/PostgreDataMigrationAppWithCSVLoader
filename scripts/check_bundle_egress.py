#!/usr/bin/env python3
"""Scan a built frontend for outbound network references (M7, #111; BR-37).

    python scripts/check_bundle_egress.py csv-table-hub-main/.output

Fails (exit 1) when the build can load something from outside this deployment:
  - an external script, stylesheet, image or font in HTML/CSS (src=, href=, @import, url()),
  - a literal external URL passed to fetch, XMLHttpRequest, sendBeacon, WebSocket, EventSource or import(),
  - a known analytics, error-reporting or CDN host anywhere.
Other URLs (XML namespace identifiers, links in library messages) are listed but are never requested,
so they don't fail the check. Build first with `npm ci && npx vite build` in csv-table-hub-main.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEXT = {".js", ".mjs", ".cjs", ".css", ".html", ".json", ".txt", ".map", ".svg"}
HOST = re.compile(r"""(?:https?|wss?)://([A-Za-z0-9._-]+)""", re.I)
LOCAL = {"localhost", "127.0.0.1"}
URL = r"""["'`](?:https?|wss?)://[^"'`\s]+"""
MARKUP = {".html", ".css", ".svg"}   # where src=, @import and url() mean "load this"; in scripts `new URL(...)` doesn't
LOADS = [
    ("HTML/CSS external resource", re.compile(
        r"""(?:\bsrc|\bhref)\s*=\s*["'](?:https?:)?//[^"']+"""
        r"""|@import\s+(?:url\()?["']?(?:https?:)?//[^;)\s]+"""
        r"""|\burl\(\s*["']?(?:https?:)?//[^)]+""", re.I), MARKUP),
    ("fetch of a literal URL", re.compile(r"\bfetch\(\s*" + URL, re.I), None),
    ("XMLHttpRequest of a literal URL", re.compile(r"""\.open\(\s*["'][A-Za-z]+["']\s*,\s*""" + URL, re.I), None),
    ("sendBeacon", re.compile(r"\bsendBeacon\(\s*" + URL, re.I), None),
    ("WebSocket or EventSource", re.compile(r"\bnew\s+(?:WebSocket|EventSource)\(\s*" + URL, re.I), None),
    ("dynamic import of a URL", re.compile(r"\bimport\(\s*" + URL, re.I), None),
]
# Hosts that must never appear: analytics, error reporting, tag managers, public CDNs and font hosts.
BANNED = re.compile(
    r"(google-analytics|googletagmanager|doubleclick|googleapis|gstatic|sentry\.io|ingest\.sentry|posthog|mixpanel|segment\.(?:io|com)|"
    r"amplitude\.com|datadoghq|newrelic|nr-data|hotjar|logrocket|fullstory|bugsnag|rollbar|intercom|clarity\.ms|"
    r"cdn\.jsdelivr|unpkg\.com|cdnjs|cloudflare(?:insights)?\.com|bootstrapcdn|fontawesome|typekit|lovable\.(?:dev|app))", re.I)


def scan(root: Path) -> dict:
    loads, banned, other = [], [], {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TEXT):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = str(path.relative_to(root))
        for label, pattern, only in LOADS:
            if only and path.suffix.lower() not in only:
                continue
            loads += [f"{rel}: {label}: {m.group(0)[:100]}" for m in pattern.finditer(text)
                      if not any(h in m.group(0) for h in ("localhost", "127.0.0.1"))]
        for m in HOST.finditer(text):
            host = m.group(1).lower().rstrip(".")
            if host in LOCAL:
                continue
            if BANNED.search(host):
                banned.append(f"{rel}: {host}")
            other[host] = other.get(host, 0) + 1
    return {"loads": loads, "banned": sorted(set(banned)), "other": other}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    failed = False
    for arg in argv:
        root = Path(arg)
        if not root.is_dir():
            print(f"{arg}: not a directory; build the frontend first", file=sys.stderr)
            return 2
        found = scan(root)
        print(f"{arg}: {len(found['loads'])} load path(s), {len(found['banned'])} analytics/CDN host(s), "
              f"{len(found['other'])} other host name(s) that are never requested")
        for line in found["loads"] + found["banned"]:
            print("  FAIL", line)
        if found["other"]:
            print("  named only (namespaces, documentation links): " +
                  ", ".join(f"{h} x{n}" for h, n in sorted(found["other"].items(), key=lambda kv: -kv[1])))
        failed = failed or bool(found["loads"] or found["banned"])
    print("FAILED: the build can reach outside this deployment" if failed else "OK: the build requests nothing outside this deployment")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
