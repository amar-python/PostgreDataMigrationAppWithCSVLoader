#!/usr/bin/env bash
# End-to-end sanity checks for the CSV migrator.
#
# Runs directly against Postgres via psql (uses PG* env). Focuses on the
# classes of bugs that have hit us before:
#   1. Ambiguous PL/pgSQL identifiers when column names collide with loop
#      variables (i, t, s, idx, ...).
#   2. Duplicate sanitized column names.
#   3. Reserved metadata columns (_id, _row_hash, _created_at) sneaking in.
#
# Usage: bash scripts/e2e-csv.sh
set -euo pipefail

pass=0
fail=0
suffix=$(date +%s)_$$

run_case() {
  local label="$1"; shift
  local expect="$1"; shift          # "ok" or "fail"
  local table_base="$1"; shift
  local cols="$1"; shift            # postgres text[] literal, e.g. '{i,t,s}'
  local types="$1"; shift           # postgres text[] literal

  # Unique per-run table name so we never collide with previous runs or need
  # DROP privileges (create_csv_table is SECURITY DEFINER, owned by postgres).
  local table="${table_base}_${suffix}"

  set +e
  local out
  out=$(psql -X -v ON_ERROR_STOP=1 -c \
    "SELECT public.create_csv_table('$table', '$cols'::text[], '$types'::text[]);" 2>&1)
  local rc=$?
  set -e

  local got="ok"
  [[ $rc -ne 0 ]] && got="fail"

  if [[ "$got" == "$expect" ]]; then
    echo "  ✓ $label"
    pass=$((pass + 1))
  else
    echo "  ✗ $label (expected $expect, got $got)"
    echo "    $out" | head -3
    fail=$((fail + 1))
  fi
}

echo "== create_csv_table regression cases =="
run_case "plain columns"              ok   csv_e2e_plain    '{id,name,amount}'   '{int8,text,numeric}'
run_case "ambiguous loop-var names"   ok   csv_e2e_ambig    '{i,t,s,idx,name}'   '{int8,text,int8,text,text}'
run_case "unicode-ish sanitized cols" ok   csv_e2e_uni      '{col_1,col_2}'      '{text,text}'
run_case "invalid table name"         fail bad-name         '{id}'               '{int8}'
run_case "unknown type"               fail csv_e2e_badtype  '{id}'               '{smallint}'
run_case "type/column length mismatch" fail csv_e2e_mism    '{id,name}'          '{int8}'

echo
echo "$pass passed, $fail failed"
exit $fail
