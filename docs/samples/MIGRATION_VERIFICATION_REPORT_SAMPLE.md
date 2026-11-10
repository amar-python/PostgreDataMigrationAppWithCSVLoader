# Migration Verification Report: SAMPLE

> **Sample.** Produced by a real run against a local PostgreSQL instance, using two **synthetic** CSV files with invented names. It shows the shape and rigour of the report, not a customer migration. Every figure below was recorded during the run and is reproducible: see section 8.

| | |
|---|---|
| Run started (UTC) | 2026-11-10T05:55:31+00:00 |
| Run finished (UTC) | 2026-11-10T05:55:32+00:00 |
| Code version | `f25c94f2d6` (clean working tree) |
| Database | PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) |
| Platform | Python 3.13.18, Linux-6.18.44-fc-v338-x86_64-with-glibc2.39 |

## 1. Result

**RECONCILED**: 13 of 13 checks passed. Of 10 source rows in the T&E file, **6 were loaded and 4 were rejected by the database**, for the reasons in section 4; nothing was lost or silently altered. The 8-row dynamic file loaded in full.

## 2. Source files

| File | Mode | Rows | Bytes | SHA-256 |
|---|---|---|---|---|
| `orgs_sample.csv` | T&E (`organisations`) | 10 | 295 | `593c2d41f415f178193b97643b7a5beb373f1c490d58b46ad27cf8ca3ec0a09b` |
| `equipment_register.csv` | Dynamic | 8 | 476 | `14fab9c3bfb55400c5fb9744420f81e073d9dca7fc9abbe30e7d341cdf5abf62` |

## 3. Verification checks

Each check compares the system's output against the database itself, a hash computed outside the system, or an outcome declared in advance. The exception is check 12, which is the system recomputing its own audit chain.

| # | Check | Observed | Result |
|---|---|---|---|
| 1 | T&E: every source row is accounted for (loaded + rejected = source) | 6 + 4 + 0 = 10 of 10 | PASS |
| 2 | T&E: rows in the database equal the rows the API reported loaded | database 6, API 6 | PASS |
| 3 | T&E: the rows rejected are exactly the rows the fixture was designed to produce | rejected [6, 7, 8, 9], expected [6, 7, 8, 9] | PASS |
| 4 | T&E: every loaded row matches its source row, field for field | 6 of 6 match | PASS |
| 5 | T&E: file hash recorded by the system equals an independently computed SHA-256 | 593c2d41f415f178… | PASS |
| 6 | T&E: registry counts equal the API response | registry loaded 6 / failed 4 | PASS |
| 7 | Dynamic: rows in the new table equal source rows | database 8, source 8 | PASS |
| 8 | Dynamic: file hash recorded by the system equals an independently computed SHA-256 | 14fab9c3bfb55400… | PASS |
| 9 | Dynamic: re-upload of the same file is refused | duplicate_file | PASS |
| 10 | Dynamic: the same content under a new filename is refused | duplicate_file (reason: content) | PASS |
| 11 | Audit: one entry per successful load; refused or fully failed uploads leave none | 2 entries for 2 loads | PASS |
| 12 | Audit: hash chain recomputed and intact | intact=True, rows checked=2 | PASS |
| 13 | T&E: re-uploading the same file, where every row now fails, is refused and changes nothing | status error; registry (id, loaded, failed) [[1, 6, 4]] vs before [[1, 6, 4]]; database rows 6 | PASS |

## 4. Rejected rows (T&E file)

The fixture contains four deliberately defective rows. The expected outcome was declared in `scripts/sample_verification_run.py` before the run. The reason column is the database's own message.

| Data row | Source line | Designed defect | Database message |
|---|---|---|---|
| 6 | `Alpha Systems Pty Ltd,prime,AU` | duplicate name (unique constraint) | duplicate key value violates unique constraint "organisations_name_key" |
| 7 | `Foxtrot Labs,startup,AU` | org_type 'startup' not in the allowed list (check constraint) | new row for relation "organisations" violates check constraint "organisations_org_type_check" |
| 8 | `Golf Integration,prime,AUS` | country 'AUS' too long for a 2-character code | value too long for type character(2) |
| 9 | `,prime,AU` | name is empty (not-null constraint) | null value in column "name" of relation "organisations" violates not-null constraint |

## 5. Rows loaded (T&E file)

Read back from `tenant_dev.organisations` after the load (6 rows):

| name | org_type | country |
|---|---|---|
| Alpha Systems Pty Ltd | prime | AU |
| Bravo Test Unit | test_unit | AU |
| Charlie Aerospace | subcontractor | US |
| Delta Research | academic | AU |
| Echo Defence | government | AU |
| Hotel Dynamics | subcontractor | GB |

## 6. Dynamic mode and duplicate handling

`equipment_register.csv` created table `csv_equipment_register_v1` with 8 rows. Column types detected:

| Column | PostgreSQL type |
|---|---|
| asset_id | text |
| description | text |
| category | text |
| calibration_due | date |
| quantity | bigint |

Re-uploading the same file returned `duplicate_file` (reason: `content`); uploading the same content as `equipment_register_copy.csv` returned `duplicate_file` (reason: `content`). Neither added an audit entry (check 11).

## 7. Audit trail

2 entries, newest first. The hash chain was recomputed from the stored rows: **intact = True** over 2 rows.

| Action | File | Target | Mode | Actor | Time (UTC) |
|---|---|---|---|---|---|
| upload | equipment_register.csv | csv_equipment_register_v1 | dynamic | admin | 2026-11-10T05:55:32.044474+00:00 |
| upload | orgs_sample.csv | tenant_dev.organisations | te | admin | 2026-11-10T05:55:31.982480+00:00 |

## 8. What this report does and does not show

**Shows:** for these two files, every source row is either in the database or rejected with the database's own reason; loaded values equal source values; file hashes are recorded correctly; duplicates are refused; a re-upload that fails every row changes nothing; the audit trail has one entry per successful load and its hash chain verifies.

**Does not show:**

- Behaviour on real or large data. The inputs are 10 and 8 invented rows.
- A hardened deployment. Observed during this run: a request with no credentials at all returned HTTP **200** (the API key is not set, so unauthenticated access is open); the API's database connections used role(s) **postgres** and the audit table is owned by **postgres**, so the database itself would not stop the API altering the audit log. The audit chain is designed to reveal such changes, but this run did not test that.
- Independent assurance. The checks were written and run by the system's developers. They are repeatable by a reviewer, not a third-party assessment.
- Conformance to any Defence standard. No claim of alignment with ASDEFCON or any DID is made here.
- Re-upload behaviour beyond check 13. Only one case was exercised: re-uploading an identical file, where every row fails. Overwriting a file with changed content, and concurrent uploads, were not exercised here.

**Reproduce:** deploy the dev schema to an empty database, create a tenant admin, start the API, then run `python scripts/sample_verification_run.py`. The raw responses behind this report are in `docs/samples/verification-run-evidence.json`.
