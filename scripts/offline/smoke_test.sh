#!/usr/bin/env bash
# smoke_test.sh <API_KEY> [API_URL] [FRONTEND_URL]: prove the installed stack works.
# Optional SMOKE_TENANT/SMOKE_USER/SMOKE_PASSWORD add the sign-in checks.
# Prints PASS/FAIL per check and exits non-zero on any failure.
set -uo pipefail
KEY="$1"; API="${2:-http://localhost:8000}"; FE="${3:-http://localhost:3000}"
fail=0
pass() { echo "PASS  $1"; }
nope() { echo "FAIL  $1"; fail=1; }
# Services may still be starting: wait up to 30 s for each.
for _ in $(seq 1 30); do curl -sf "$API/api/health" >/dev/null && break; sleep 1; done
for _ in $(seq 1 30); do curl -sf -o /dev/null "$FE/" && break; sleep 1; done

curl -sf "$API/api/health" >/dev/null && pass "API health" || nope "API health"

code=$(curl -s -o /dev/null -w '%{http_code}' "$API/api/csv/files")
[ "$code" = 401 ] && pass "API rejects a missing key" || nope "API rejects a missing key (got $code)"

TAG="$(date +%s%N)"   # unique name and content, so the test can be re-run
body=$(printf '{"fileName":"smoke_%s.csv","content":"a,b\\n1,%s\\n2,y\\n"}' "$TAG" "$TAG")
res=$(curl -s -H "X-API-Key: $KEY" -H 'content-type: application/json' -d "$body" "$API/api/csv/upload")
echo "$res" | grep -q '"insertedRows":2' && pass "upload a CSV (2 rows inserted)" || nope "upload a CSV: $res"

curl -sf -H "X-API-Key: $KEY" "$API/api/csv/files" | grep -q '"total_rows":2' \
  && pass "upload listed with persisted counts" || nope "upload listed with persisted counts"

curl -sf "$FE/" | grep -qi '<html' && pass "frontend serves the app" || nope "frontend serves the app"

# With SMOKE_TENANT, SMOKE_USER and SMOKE_PASSWORD set, also prove per-user sign-in (#96).
if [ -n "${SMOKE_USER:-}" ]; then
  login=$(printf '{"tenant":"%s","username":"%s","password":"%s"}' "$SMOKE_TENANT" "$SMOKE_USER" "$SMOKE_PASSWORD")
  token=$(curl -s -H 'content-type: application/json' -d "$login" "$API/api/auth/login" \
          | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  [ -n "$token" ] && pass "admin signs in" || nope "admin signs in"
  curl -sf -H "Authorization: Bearer $token" "$API/api/auth/me" | grep -q '"role":"tenant_admin"' \
    && pass "session is tenant_admin" || nope "session is tenant_admin"
fi
exit $fail
