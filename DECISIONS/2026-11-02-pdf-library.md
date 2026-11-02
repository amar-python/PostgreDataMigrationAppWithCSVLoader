# Decision: PDF generation library

Status:  Decided
Date:    2026-11-02
Review:  On trigger (see below), not scheduled

## Choice

**ReportLab** for all server-side PDF generation, starting with the
Migration Verification Report (P1).

## Reasoning

Each trade-off was weighed against the project's actual constraints:

- "Air-gap install" — ReportLab is one pure-Python wheel; WeasyPrint
  needs Pango, Cairo and GDK-PixBuf system libraries vendored for
  every target OS. #60 (offline install, due 15 Nov) is simpler
  with ReportLab.
- "V&V evidence" — ReportLab produces byte-identical PDFs across
  runs. A report's SHA-256 is stable and quotable in audit logs.
  WeasyPrint output can shift by a pixel between runs due to font
  hinting and CSS layout; fine for most contexts, weaker for V&V.
- "Deterministic toolchain" — matches the discipline this project
  sells. A declared, provable output format is a stronger artefact
  than a near-identical one.

## Trade-offs accepted

- Slower visual iteration on report templates (edit Python,
  regenerate PDF, review).
- Verbose templates: multi-section reports are hundreds of lines
  of ReportLab primitives.
- No HTML/CSS reuse with the frontend. If a frontend ever renders
  a Migration Verification Report preview, the on-screen view and
  the PDF will be two separate implementations.
- Less accessible to a non-Python collaborator than HTML/CSS.

## Reopen trigger

Reconsider this decision if any of the following becomes true:

- Reports become visually dynamic and need frequent layout iteration
- The report format must match a frontend screen exactly
- The air-gap constraint is dropped
- A non-Python contributor needs to modify report templates regularly

Tracked in #67.