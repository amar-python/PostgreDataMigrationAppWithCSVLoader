# Decision: SECURITY.md reporting channel is GitHub private vulnerability reporting

Status:  Decided (the project owner chose it when asked, 2026-11-23)
Date:    2026-11-23
Review:  2027-01-04 (quarterly audit cycle, with the SECURITY.md decision)
Changes: the "Reporting channel" section of `2026-10-04-security-md.md`

## What changed

The earlier decision said "Email only. Address TBD ... GitHub PVR not enabled", and
`SECURITY.md` carried a personal mailbox as a placeholder until a dedicated address existed (#57,
#300, OIT-015). No dedicated mailbox is going to exist for this project.

Reports now go through GitHub's private vulnerability reporting (the repository's Security tab,
"Report a vulnerability"). `SECURITY.md` points to it and no longer lists any email address.

## Why

- It needs no organisation mailbox, so the dependency that blocked #300 goes away.
- Only the maintainers see a report, and the reporter and the maintainers can work on a fix in a
  private advisory before anything is public.
- A personal mailbox is no longer printed in a public file.

## What it costs

- It needs a GitHub account. A reporter without one has no channel. `SECURITY.md` does not offer one
  (it still says not to open a public issue); add one if that turns out to matter.
- The mailbox mitigation in the 2026-10-04 decision (auto-forward with a keyword filter) no longer
  applies. Notifications for new reports go to the repository's admins through GitHub, so their
  notification settings are now the thing to check.
- The feature is off until someone with admin rights turns it on.

## Owner action still needed

1. Repository Settings, Code security, **Private vulnerability reporting**: enable it.
2. Submit one test report from another account (or ask someone to) and confirm a notification arrives.
   #300's acceptance step ("test mail received") becomes "test report received".

Until step 1 is done, the link in `SECURITY.md` leads reporters to a page that does not accept reports.
