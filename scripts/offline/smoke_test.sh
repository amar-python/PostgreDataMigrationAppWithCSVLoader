#!/usr/bin/env bash
# smoke_test.sh [API_URL] [FRONTEND_URL]: prove the installed stack works.
# SMOKE_TENANT/SMOKE_USER/SMOKE_PASSWORD (the installer's first tenant admin) are needed for the
# sign-in, upload and listing checks: every data call signs in, the shared X-API-Key was retired (#298).
# Without them those checks are skipped and said so.
# Prints PASS/FAIL per check and exits non-zero on any failure.
set -uo pipefail
API="${1:-http://localhost:8000}"; FE="${2:-http://localhost:3000}"
fail=0
pass() { echo "PASS  $1"; }
nope() { echo "FAIL  $1"; fail=1; }
# Services may still be starting: wait up to 30 s for each.
for _ in $(seq 1 30); do curl -sf "$API/api/health" >/dev/null && break; sleep 1; done
for _ in $(seq 1 30); do curl -sf -o /dev/null "$FE/" && break; sleep 1; done

curl -sf "$API/api/health" >/dev/null && pass "API health" || nope "API health"

code=$(curl -s -o /dev/null -w '%{http_code}' "$API/api/csv/files")
[ "$code" = 401 ] && pass "API rejects a request without a session" \
  || nope "API rejects a request without a session (got $code)"

if [ -n "${SMOKE_TENANT:-}" ] && [ -n "${SMOKE_USER:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ]; then
  login=$(printf '{"tenant":"%s","username":"%s","password":"%s"}' "$SMOKE_TENANT" "$SMOKE_USER" "$SMOKE_PASSWORD")
  token=$(curl -s -H 'content-type: application/json' -d "$login" "$API/api/auth/login" \
          | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  [ -n "$token" ] && pass "admin signs in" || nope "admin signs in"
  curl -sf -H "Authorization: Bearer $token" "$API/api/auth/me" | grep -q '"role":"tenant_admin"' \
    && pass "session is tenant_admin" || nope "session is tenant_admin"

  TAG="$(date +%s%N)"   # unique name and content, so the test can be re-run
  body=$(printf '{"fileName":"smoke_%s.csv","content":"a,b\\n1,%s\\n2,y\\n"}' "$TAG" "$TAG")
  res=$(curl -s -H "Authorization: Bearer $token" -H 'content-type: application/json' -d "$body" "$API/api/csv/upload")
  echo "$res" | grep -q '"insertedRows":2' && pass "upload a CSV (2 rows inserted)" || nope "upload a CSV: $res"

  curl -sf -H "Authorization: Bearer $token" "$API/api/csv/files" | grep -q '"total_rows":2' \
    && pass "upload listed with persisted counts" || nope "upload listed with persisted counts"
else
  echo "SKIP  sign-in, upload and listing checks (SMOKE_TENANT, SMOKE_USER and SMOKE_PASSWORD not all set)"
fi

curl -sf "$FE/" | grep -qi '<html' && pass "frontend serves the app" || nope "frontend serves the app"
exit $fail
