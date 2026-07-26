#!/usr/bin/env bash
# =============================================================================
# schema/redis/te_seed_data.sh — Redis Seed Data
#
# Called by adapter_redis.sh with these env vars pre-set:
#   KEY_PREFIX  — e.g. te:dev
#   REDIS_ARGS  — connection args for redis-cli
#
# Redis data model:
#   Hashes   — entity records:  {prefix}:{entity}:{id}
#   Sets     — index lookups:   {prefix}:idx:{entity}:all
#   Sorted Sets — by date/score: {prefix}:idx:{entity}:by_date
# =============================================================================

P="$KEY_PREFIX"   # shorthand
R="redis-cli $REDIS_ARGS"

echo "  Loading Redis seed data with prefix: ${P}"

# ── organisations ─────────────────────────────────────────────────────────────
$R HSET "${P}:org:10000001" \
   org_id "10000001" name "Capability Acquisition and Sustainment Group (CASG)" \
   org_type "government" country "AU" is_active "1"
$R SADD "${P}:idx:org:all" "10000001"

$R HSET "${P}:org:10000002" \
   org_id "10000002" name "Defence Science and Technology (DST) Group" \
   org_type "government" country "AU" is_active "1"
$R SADD "${P}:idx:org:all" "10000002"

$R HSET "${P}:org:10000003" \
   org_id "10000003" name "Leidos Australia" \
   org_type "prime" country "AU" is_active "1"
$R SADD "${P}:idx:org:all" "10000003"

# ── personnel ─────────────────────────────────────────────────────────────────
$R HSET "${P}:person:20000001" \
   person_id "20000001" org_id "10000001" \
   full_name "Brigadier Helen Marsh" email "h.marsh@defence.gov.au" \
   te_role "test_director" clearance "PV" is_active "1"
$R SADD "${P}:idx:person:all" "20000001"
$R SET  "${P}:idx:person:email:h.marsh@defence.gov.au" "20000001"

$R HSET "${P}:person:20000002" \
   person_id "20000002" org_id "10000001" \
   full_name "Col. Patrick O'Brien" email "p.obrien@defence.gov.au" \
   te_role "test_manager" clearance "NV2" is_active "1"
$R SADD "${P}:idx:person:all" "20000002"
$R SET  "${P}:idx:person:email:p.obrien@defence.gov.au" "20000002"

$R HSET "${P}:person:20000003" \
   person_id "20000003" org_id "10000002" \
   full_name "Dr. Anika Sharma" email "a.sharma@dst.defence.gov.au" \
   te_role "test_engineer" clearance "NV2" is_active "1"
$R SADD "${P}:idx:person:all" "20000003"

# ── test programs ─────────────────────────────────────────────────────────────
$R HSET "${P}:program:CYB9131" \
   program_code "CYB9131" program_name "COSPO Cyber OT&E Programme" \
   classification "PROTECTED" status "active" \
   start_date "2024-07-01" end_date "2026-06-30" \
   org_id "10000001" director_id "20000001"
$R SADD "${P}:idx:program:all"    "CYB9131"
$R SADD "${P}:idx:program:active" "CYB9131"

$R HSET "${P}:program:LAND400-P3" \
   program_code "LAND400-P3" program_name "LAND 400 Phase 3 IFV T&E" \
   classification "SECRET" status "active" \
   start_date "2024-01-15" end_date "2027-12-31" \
   org_id "10000001" director_id "20000001"
$R SADD "${P}:idx:program:all"    "LAND400-P3"
$R SADD "${P}:idx:program:active" "LAND400-P3"

# ── defect reports ────────────────────────────────────────────────────────────
$R HSET "${P}:defect:DR-CYB-0001" \
   defect_ref "DR-CYB-0001" program_code "CYB9131" \
   title "Audit Log gap on /api/v2/archive/" \
   severity "major" status "in_progress" raised_by_id "20000003"
$R SADD "${P}:idx:defect:all"       "DR-CYB-0001"
$R SADD "${P}:idx:defect:open"      "DR-CYB-0001"
$R SADD "${P}:idx:defect:major"     "DR-CYB-0001"

$R HSET "${P}:defect:DR-CYB-0002" \
   defect_ref "DR-CYB-0002" program_code "CYB9131" \
   title "TLS 1.2 accepted on legacy export endpoint" \
   severity "major" status "open" raised_by_id "20000002"
$R SADD "${P}:idx:defect:all"   "DR-CYB-0002"
$R SADD "${P}:idx:defect:open"  "DR-CYB-0002"
$R SADD "${P}:idx:defect:major" "DR-CYB-0002"

# ── test results counters (sorted set by verdict score) ───────────────────────
$R ZADD "${P}:stats:CYB9131:verdicts" 4 "pass"
$R ZADD "${P}:stats:CYB9131:verdicts" 2 "fail"
$R ZADD "${P}:stats:CYB9131:verdicts" 1 "inconclusive"

echo "  ✓ Redis seed data loaded (prefix: ${P})"
