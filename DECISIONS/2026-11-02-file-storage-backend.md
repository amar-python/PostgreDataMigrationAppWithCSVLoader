# Decision: File storage backend

Status:  Decided
Date:    2026-11-02
Review:  On trigger (see below), not scheduled

## Choice

**BYTEA in PostgreSQL** for file bodies. One backend across all environments.

## Context

#68 asked whether to introduce Azurite as a local Blob emulator to match a BYTEA-local / Blob-prod split. Investigation showed no such split exists: the system runs BYTEA in every environment today. The real decision is upstream — Postgres BYTEA or Azure Blob Storage for file bodies.

## Reasoning

- **Transactional integrity.** `api/services/originals.py` commits upload record, blob, source rows and audit together. Moving blob to Azure Storage breaks that guarantee or needs an outbox pattern.
- **Air-gap simplicity.** No Azure Storage SDK, no network reach required for file I/O, no credential rotation. Reinforces #60 (offline install).
- **Operational surface.** One backup system (Flexible Server PITR covers file bodies for free), one restore story, one monitoring target.
- **Scale fits current need.** `MAX_UPLOAD_BYTES = 50 MB`; expected tenant volume is tens of GB per year. Postgres handles this cleanly.

## Trade-offs accepted

- DB size scales with upload volume. Backup and restore times grow with it.
- No streaming insert — full file bytes loaded in memory per upload.
- Can't serve files directly with signed URLs.
- Potentially leaves provisioned Terraform storage accounts unused (separate follow-up issue).

## Reopen trigger

Reconsider if any of:

- A tenant's upload volume grows to where PITR restore times exceed 1 hour
- Direct-serve of uploaded files (signed URLs, CDN) becomes a feature requirement
- A deployment target needs multi-region file replication that Postgres HA can't deliver

## Related

- #68 (closed with this decision)
- #60 (offline install — reinforced by this decision)
- D3 (ReportLab for PDF — same air-gap discipline)