# Test cases: M4 review API (#108, PR #142)

**Scope:** the review API that M4a adds (`GET /api/csv/uploads/{id}/rows`, `PUT …/rows/{n}/decision`, `PUT …/rows/{n}/cells/{column}`, `GET …/rows/{n}/history`), its database tables (`row_decisions`, `cell_edits`) and the CORS change for `PUT`.
**Requirements:** BR-25, BR-26, BR-27 (review), BR-35 (append-only audit), BR-36 (roles and tenant isolation).
**Decisions they test** (product owner, 28 Oct, on #108): review is recorded now and applied in M6; only `reviewer` and `tenant_admin` may change; a reason is required.

There are 17 positive and 16 negative cases. Every case has an automated test, and CI runs them all. Where you can also check a case by hand on your PC, the **Manual** column gives the command.

## How to run

### Automated (all cases)

CI runs them on every push. To run them on your PC, PostgreSQL must be running with the `PG*` values from QUICKSTART step 3 set. The tests make their own throwaway tenants and users, and remove them afterwards.

```powershell
cd "C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader"
python -m pytest -q tests/test_review.py tests/test_review_cases.py tests/test_runtime_role.py tests/test_roles.py tests/test_api_coverage.py
```

**Pass:** pytest ends with `passed` and no `failed`.

### Manual (after #142 is merged, with the API running)

Run this once in a PowerShell window. It signs in as your tenant admin and uploads a three-row file whose row 2 is invalid. Use your own tenant and username if they differ from `dev` and `admin`.

```powershell
cd "C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader"
$api = "http://localhost:8000"
$sec = Read-Host -AsSecureString "Password for admin"
$pw = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
$login = Invoke-RestMethod -Method Post "$api/api/auth/login" -ContentType "application/json" -Body (@{tenant="dev"; username="admin"; password=$pw} | ConvertTo-Json)
$h = @{ Authorization = "Bearer $($login.token)" }
function Call($method, $path, $body) {
    $req = @{ Method = $method; Uri = "$api$path"; Headers = $h }
    if ($body) { $req.ContentType = "application/json"; $req.Body = ($body | ConvertTo-Json) }
    try { Invoke-RestMethod @req } catch { "HTTP " + [int]$_.Exception.Response.StatusCode }
}
$tag = Get-Random
$up = Call Post "/api/csv/upload" @{ fileName = "tc-m4-$tag.csv"; content = "n,t`n1,first-$tag`nx,second`n3,third`n"; types = @("int8","text") }
$u = $up.uploadId
"upload: $($up.status), id $u"
```

**Expected:** `upload: ok, id <number>`. Every command in the table below runs in **this same window**, so `$u` and `Call` are still defined. A refused request prints `HTTP <code>` instead of throwing an error.

## Positive cases

| ID | Requirement | What it checks | Manual command | Expected | Automated test |
|---|---|---|---|---|---|
| P01 | BR-25 | Every row is listed, with column types and validation | `$p = Call Get "/api/csv/uploads/$u/rows"; $p.total; $p.types -join ","; $p.rows[1].errors.reason` | `3`, `int8,text`, `"x" is not a whole number` | `test_review.py::test_pages_through_every_row_with_validation` |
| P02 | BR-25 | Paging limits: the page size is capped at 500, an offset past the end returns no rows, and a negative offset starts at 0 | `(Call Get "/api/csv/uploads/$u/rows?limit=10000").limit; (Call Get "/api/csv/uploads/$u/rows?offset=3").rows.Count` | `500`, `0` | `test_review_cases.py::test_P02_paging_bounds` |
| P03 | BR-25 | Rows beyond the 200 errors reported at upload are still validated | Automated only (needs a 250-row file) | Row 250 shows its error | `test_review.py::test_validates_rows_beyond_the_reported_error_cap` |
| P04 | BR-25 | A row wider than the header is flagged | `$r = Call Post "/api/csv/upload" @{fileName="tc-rag-$tag.csv"; content=(("a,b","1,ok-$tag","2,y,extra","") -join [char]10); types=@("text","text")}; (Call Get "/api/csv/uploads/$($r.uploadId)/rows").rows[1].errors.column` | `(beyond header)` | `test_review_cases.py::test_P04_ragged_row_is_flagged` |
| P05 | BR-25, BR-26 | An upload where every row failed can still be reviewed | `$f = Call Post "/api/csv/upload" @{fileName="tc-fail-$tag.csv"; content=(("n","bad-$tag","") -join [char]10); types=@("int8")}; (Call Get "/api/csv/uploads/$($f.uploadId)/rows").total` | `1` (the upload's status was `error`) | `test_review_cases.py::test_P05_a_failed_upload_can_be_reviewed` |
| P06 | BR-26 | Exclude, then include: the latest decision wins, and both are kept in the history | `Call Put "/api/csv/uploads/$u/rows/3/decision" @{decision="exclude"; reason="duplicate"}; Call Put "/api/csv/uploads/$u/rows/3/decision" @{decision="include"; reason="not a duplicate"}; (Call Get "/api/csv/uploads/$u/rows/3/history").decision -join ","` | `exclude,include`; the row's `decision` is `include` | `test_review.py::test_row_decisions_record_actor_and_reason_and_the_latest_wins` |
| P07 | BR-27 | An edit becomes a new version, the original is unchanged, and the row is revalidated | `$e = Call Put "/api/csv/uploads/$u/rows/2/cells/n" @{value="2"; reason="typo"}; $e.original[0]; $e.current[0]; $e.errors.Count` | `x`, `2`, `0` | `test_review.py::test_cell_edits_are_versions_over_the_unchanged_original` |
| P08 | BR-27 | An edit to a value of the wrong type is flagged | `(Call Put "/api/csv/uploads/$u/rows/1/cells/n" @{value="one"; reason="test"}).errors.reason` | `"one" is not a whole number` | `test_review_cases.py::test_P08_an_edit_to_a_bad_value_is_flagged` |
| P09 | BR-27 | A column can be given by index, and a text cell can be set to empty | `(Call Put "/api/csv/uploads/$u/rows/3/cells/1" @{value=""; reason="blank it"}).current -join ","` | `3,` | `test_review_cases.py::test_P09_edit_by_column_index_and_to_an_empty_value` |
| P10 | BR-26 | The reason is stored trimmed | `Call Put "/api/csv/uploads/$u/rows/1/decision" @{decision="exclude"; reason="   spaces   "}; (Call Get "/api/csv/uploads/$u/rows/1/history")[-1].reason` | `spaces` | `test_review_cases.py::test_P10_reason_is_stored_trimmed` |
| P11 | BR-26, BR-27 | The actor is the signed-in user | `(Call Get "/api/csv/uploads/$u/rows/2/history").actor` | `admin` | `test_review_cases.py::test_P11_actor_is_the_signed_in_user` |
| P12 | BR-36 | Every role (uploader, reviewer, tenant admin, auditor) can view rows and history | Automated only (no tool yet creates members with other roles) | 200 for each role | `test_review_cases.py::test_P12_every_role_can_view_rows_and_history` |
| P13 | BR-35 | Each change writes an audit row with before and after values, and the hash chain stays intact | `(Call Get "/api/audit/verify").intact` | `True` | `test_review.py::test_changes_are_audited_and_insert_only` |
| P14 | Decision 1 | The imported table doesn't change | `(Call Get "/api/csv/files").Where({ $_.upload_id -eq $u }).row_count` | `2` (rows 1 and 3, as imported at upload) | `test_review.py::test_cell_edits_are_versions_over_the_unchanged_original` |
| P15 | BR-35 | Review changes work through the runtime role `te_app` | On your PC, the API runs as `te_app` since M3d. P06 and P07 passing there is the check | P06 and P07 pass | `test_runtime_role.py::test_the_api_works_as_the_runtime_role` |
| P16 | — | The browser may send `PUT` (CORS preflight) | Use the Review screen from #143: Exclude a row | The change saves | `test_api_coverage.py::test_preflight_allows_put_for_review_changes` |
| P17 | BR-26 | An untouched row has an empty history | `(Call Get "/api/csv/uploads/$($f.uploadId)/rows/1/history").Count` | `0` | `test_review.py::test_refusals` |

## Negative cases

| ID | Requirement | What it checks | Manual command | Expected | Automated test |
|---|---|---|---|---|---|
| N01 | BR-26, decision 3 | A decision with a blank reason is refused | `Call Put "/api/csv/uploads/$u/rows/2/decision" @{decision="exclude"; reason="  "}` | `HTTP 422` | `test_review.py::test_refusals` |
| N02 | BR-27, decision 3 | An edit with an empty reason is refused | `Call Put "/api/csv/uploads/$u/rows/2/cells/n" @{value="5"; reason=""}` | `HTTP 422` | `test_review.py::test_refusals` |
| N03 | BR-26 | An unknown decision is refused | `Call Put "/api/csv/uploads/$u/rows/2/decision" @{decision="maybe"; reason="r"}` | `HTTP 422` | `test_review.py::test_refusals` |
| N04 | BR-27 | An edit that doesn't change the value is refused | `Call Put "/api/csv/uploads/$u/rows/2/cells/t" @{value="second"; reason="r"}` | `HTTP 422` | `test_review.py::test_refusals` |
| N05 | BR-26, BR-27 | Row 0 (the header) and rows past the end are refused | `Call Put "/api/csv/uploads/$u/rows/0/decision" @{decision="exclude"; reason="r"}; Call Put "/api/csv/uploads/$u/rows/4/cells/n" @{value="1"; reason="r"}` | `HTTP 404`, `HTTP 404` | `test_review_cases.py::test_N05_row_numbers_outside_the_upload` |
| N06 | BR-27 | An unknown column name or index is refused | `Call Put "/api/csv/uploads/$u/rows/1/cells/nope" @{value="1"; reason="r"}; Call Put "/api/csv/uploads/$u/rows/1/cells/2" @{value="1"; reason="r"}` | `HTTP 404`, `HTTP 404` | `test_review.py::test_refusals`, `test_review_cases.py::test_N06_column_index_out_of_range` |
| N07 | BR-25..27 | An unknown upload is refused on every route | `Call Get "/api/csv/uploads/999999999/rows"; Call Put "/api/csv/uploads/999999999/rows/1/decision" @{decision="exclude"; reason="r"}` | `HTTP 404`, `HTTP 404` | `test_review_cases.py::test_N07_unknown_upload_on_every_route` |
| N08 | BR-36, decision 2 | An uploader can't decide or edit, and nothing is recorded | Automated only (needs an uploader account) | 403 | `test_review_cases.py::test_N08_N09_uploader_and_auditor_cannot_change`, `test_roles.py` |
| N09 | BR-36, decision 2 | An auditor can't decide or edit | Automated only (needs an auditor account) | 403 | Same as N08 |
| N10 | BR-36 | An invalid session is refused | `$good = $h; $h = @{ Authorization = "Bearer not-a-real-token" }; Call Get "/api/csv/uploads/$u/rows"; $h = $good` | `HTTP 401` | `test_review_cases.py::test_N10_an_invalid_session_is_refused` |
| N11 | BR-36 | Another tenant can't see or change the upload, and the upload is unchanged | Optional: create a second tenant with `create_tenant_admin.py`, sign in as its admin, then `Call Get "/api/csv/uploads/$u/rows"` | `HTTP 404` | `test_review_cases.py::test_N11_another_tenant_cannot_see_or_change_the_upload` |
| N12 | — | A missing field, or a field of the wrong type, is refused | `Call Put "/api/csv/uploads/$u/rows/1/decision" @{decision="exclude"}` | `HTTP 422` | `test_review_cases.py::test_N12_missing_or_wrong_body_fields` |
| N13 | BR-35 | The review tables refuse UPDATE, DELETE and TRUNCATE, even for the owner | Automated only (needs direct SQL) | Refused with `insufficient_privilege` | `test_review.py::test_changes_are_audited_and_insert_only`, `test_review_cases.py::test_N13_review_tables_reject_update_delete_and_truncate` |
| N14 | Decision 3 | The database itself refuses a blank reason | Automated only (needs direct SQL) | Refused by a CHECK constraint | `test_review_cases.py::test_N14_database_rejects_a_blank_reason` |
| N15 | BR-35 | The runtime role can't change the review tables | Automated only (needs direct SQL as `te_app`) | Refused by privilege, not by the trigger | `test_runtime_role.py::test_runtime_role_cannot_change_or_unprotect_append_only_tables` |
| N16 | — | A non-numeric upload id is refused | `Call Get "/api/csv/uploads/abc/rows"` | `HTTP 422` | `test_review_cases.py::test_N16_a_non_numeric_upload_id` |

## Not covered here
- **The review screen** (M4b, PR #143) has its own component tests (`review-table.test.tsx`) and the browser check `scripts/e2e/m4-review.js`.
- **T&E-mode uploads** store no column types, so their values are reviewed as text with no type checks. That's a known limit, noted on #142.
- **Applying review to the import** belongs to M6 (#110). It isn't tested here, because it isn't built yet.

## Record of runs
| Date | Commit | Who | Automated | Manual | Notes |
|---|---|---|---|---|---|
| 28 Oct 2026 | PR #142 branch | Claude, in the cloud workspace (PostgreSQL 16, PowerShell 7) | Local CI replica, quoted on PR #142 | 23 of 23 commands gave the expected result | Run as test account `e2eadmin4`, so P11 showed that name. Not yet run on Windows PowerShell 5.1 |
