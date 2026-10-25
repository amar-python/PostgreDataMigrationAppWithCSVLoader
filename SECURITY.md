# Security Policy

## Supported Versions

This project is actively maintained on the `main` branch. Security
fixes are applied to `main` and any current release tag. Older
tags are not supported — if you're running an older version,
upgrade to the latest release before reporting.

| Version       | Supported          |
| ------------- | ------------------ |
| main (HEAD)   | :white_check_mark: |
| Latest tag    | :white_check_mark: |
| Older tags    | :x:                |

## Reporting a Vulnerability

If you believe you've found a security vulnerability in this
project, please report it privately. Do not open a public issue.

**Email:** REPLACE_ME

Please include, where possible:

- A description of the vulnerability
- Steps to reproduce (or a proof-of-concept)
- The commit SHA or release tag you tested against
- Any suggested remediation

PGP encryption is not currently offered. If you need to send
sensitive details, let me know in your first email and we'll
agree a secure channel.

## Response Commitment

As a solo-maintainer project, these timeframes are best-effort
commitments.

- **Acknowledgement:** within 72 hours of receipt
- **Initial triage:** within 7 days
- **Fix target** (depending on severity):
  - Critical: 30 days
  - High: 60 days
  - Medium: 90 days
  - Low: next scheduled release
- **Disclosure:** coordinated with the reporter; standard
  practice is public disclosure within 90 days of the fix
  being released, or sooner if the reporter prefers

If a fix takes longer than the target (for example, a complex
remediation or a dependency on an upstream change), I'll keep
you updated and agree a revised timeline with you.

## Scope

The following are considered in-scope for this policy:

- Source code in this repository
- Infrastructure-as-code (`infra/`) that is deployed as part
  of this project
- Dependencies pinned in `api/requirements.txt` where the
  vulnerability affects this project's use of them

The following are **out of scope**:

- Third-party services this project integrates with (report
  to their maintainers directly)
- Social-engineering attacks against the author
- Denial-of-service findings that depend on exhausting a
  shared cloud resource (e.g. Azure quota limits)
- Known limitations already documented in the README under
  "Known Limitations" — report these as regular issues

## Safe Harbour

I will not pursue legal action against security researchers who:

- Make a good-faith effort to avoid privacy violations,
  destruction of data, or interruption of service
- Report findings through the channel above before public
  disclosure
- Give reasonable time for the issue to be addressed before
  going public

## Hall of Thanks

Researchers who report valid security issues will be credited
in release notes (unless they prefer to remain anonymous).

---

*This policy is adapted from standard open-source security
conventions. Last updated: 2026-10-26. Last audited: 2026-10-26
(reviewed quarterly, even when nothing changes).*
