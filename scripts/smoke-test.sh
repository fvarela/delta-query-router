#!/bin/bash
# =============================================================================
# Delta Router — Integration Smoke Test
# =============================================================================
#
# Usage:
#   ./scripts/smoke-test.sh [BASE_URL]
#
# Default BASE_URL: http://localhost:8501 (port-forwarded web-ui)
#
# Environment variables (optional — Databricks tests SKIP without these):
#   DATABRICKS_HOST      — e.g. https://adb-1234.azuredatabricks.net
#   DATABRICKS_TOKEN     — Databricks PAT
#   SQL_WAREHOUSE_ID     — SQL warehouse ID
#
# Admin credentials (optional — defaults match K8s secret):
#   ADMIN_USERNAME       — default: admin
#   ADMIN_PASSWORD       — default: deltarouter-admin
#
# Exit code: 0 if all tests PASS or SKIP, non-zero if any FAIL.
# =============================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:8501}"
ADMIN_USER="${ADMIN_USERNAME:-admin}"
ADMIN_PASS="${ADMIN_PASSWORD:-deltarouter-admin}"

# Strip trailing slash
BASE_URL="${BASE_URL%/}"

# Counters
PASS=0; FAIL=0; SKIP=0; TOTAL=0
TOKEN=""

# --- Helpers ----------------------------------------------------------------

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  FAIL: $1"; echo "        $2"; }
skip() { SKIP=$((SKIP + 1)); TOTAL=$((TOTAL + 1)); echo "  SKIP: $1"; }

# curl wrapper: returns (status_code, body) separated by newline
# Usage: resp=$(call GET /path) or resp=$(call POST /path '{"json":"body"}')
call() {
  local method="$1" path="$2" body="${3:-}"
  local headers=(-s -w '\n%{http_code}' -H 'Content-Type: application/json')
  if [[ -n "$TOKEN" ]]; then
    headers+=(-H "Authorization: Bearer $TOKEN")
  fi
  if [[ -n "$body" ]]; then
    headers+=(-d "$body")
  fi
  curl -X "$method" "${headers[@]}" "${BASE_URL}${path}" 2>/dev/null || echo -e "\n000"
}

# Extract HTTP status (last line) and body (everything else) from call output
parse_resp() {
  local resp="$1"
  HTTP_STATUS=$(echo "$resp" | tail -n1)
  HTTP_BODY=$(echo "$resp" | sed '$d')
}

has_databricks() {
  [[ -n "${DATABRICKS_HOST:-}" && -n "${DATABRICKS_TOKEN:-}" ]]
}

has_warehouse() {
  [[ -n "${SQL_WAREHOUSE_ID:-}" ]]
}

# --- Banner -----------------------------------------------------------------

echo "============================================"
echo " Delta Router Smoke Test"
echo "============================================"
echo " Target:     $BASE_URL"
echo " Databricks: $(has_databricks && echo "$DATABRICKS_HOST" || echo "(not configured — steps 4-8 will SKIP)")"
echo " Warehouse:  $(has_warehouse && echo "$SQL_WAREHOUSE_ID" || echo "(not set)")"
echo "============================================"
echo

# --- Step 1: Health check ---------------------------------------------------

echo "[Step 1] Health check"
resp=$(call GET /api/health)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /api/health -> 200"
else
  fail "GET /api/health -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 2: Login ----------------------------------------------------------

echo "[Step 2] Login"
resp=$(call POST /api/auth/login "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  TOKEN=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])" 2>/dev/null || echo "")
  if [[ -n "$TOKEN" ]]; then
    pass "POST /api/auth/login -> 200 (token acquired)"
  else
    fail "POST /api/auth/login -> 200 but no token in body" "$HTTP_BODY"
  fi
else
  fail "POST /api/auth/login -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 3: Backend health -------------------------------------------------

echo "[Step 3] Backend health"
resp=$(call GET /api/health/services)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /api/health/services -> 200"
  echo "        $HTTP_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for k,v in d.items():
  if isinstance(v,dict):
    print(f'        {k}: {v.get(\"status\",v)}')
" 2>/dev/null || echo "        (could not parse response)"
else
  fail "GET /api/health/services -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 4: Configure Databricks -------------------------------------------

echo "[Step 4] Configure Databricks workspace"
if has_databricks; then
  resp=$(call POST /api/settings/databricks "{\"host\":\"$DATABRICKS_HOST\",\"token\":\"$DATABRICKS_TOKEN\"}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "POST /api/settings/databricks -> 200"
  else
    fail "POST /api/settings/databricks -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No DATABRICKS_HOST / DATABRICKS_TOKEN set"
fi
echo

# --- Step 5: Set warehouse --------------------------------------------------

echo "[Step 5] Set SQL warehouse"
if has_databricks && has_warehouse; then
  resp=$(call PUT /api/settings/warehouse "{\"warehouse_id\":\"$SQL_WAREHOUSE_ID\"}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "PUT /api/settings/warehouse -> 200"
  else
    fail "PUT /api/settings/warehouse -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No Databricks credentials or SQL_WAREHOUSE_ID set"
fi
echo

# --- Step 6: List catalogs --------------------------------------------------

echo "[Step 6] List catalogs"
if has_databricks; then
  resp=$(call GET /api/databricks/catalogs)
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    count=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
    pass "GET /api/databricks/catalogs -> 200 ($count catalogs)"
  else
    fail "GET /api/databricks/catalogs -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No Databricks credentials"
fi
echo

# --- Step 7: List warehouses ------------------------------------------------

echo "[Step 7] List warehouses"
if has_databricks; then
  resp=$(call GET /api/databricks/warehouses)
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    count=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
    pass "GET /api/databricks/warehouses -> 200 ($count warehouses)"
  else
    fail "GET /api/databricks/warehouses -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No Databricks credentials"
fi
echo

# --- Step 8: Execute query on Databricks ------------------------------------

echo "[Step 8] Execute query (forced Databricks)"
if has_databricks && has_warehouse; then
  resp=$(call POST /api/query '{"sql":"SELECT 1 AS smoke_test","routing_mode":"databricks"}')
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "POST /api/query (databricks) -> 200"
  else
    fail "POST /api/query (databricks) -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No Databricks credentials or warehouse"
fi
echo

# --- Step 9: Execute query with smart routing --------------------------------

echo "[Step 9] Execute query (smart routing)"
resp=$(call POST /api/query '{"sql":"SELECT 1 AS smoke_test","routing_mode":"smart"}')
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  engine=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('routing_decision',{}).get('engine','?'))" 2>/dev/null || echo "?")
  pass "POST /api/query (smart) -> 200 (routed to: $engine)"
else
  fail "POST /api/query (smart) -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 10: Query history --------------------------------------------------

echo "[Step 10] Query history"
resp=$(call GET /api/logs)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  count=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
  pass "GET /api/logs -> 200 ($count entries)"
else
  fail "GET /api/logs -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 11: Routing rules --------------------------------------------------

echo "[Step 11] Routing rules"
resp=$(call GET /api/routing/rules)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  count=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
  pass "GET /api/routing/rules -> 200 ($count rules)"
else
  fail "GET /api/routing/rules -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 12: Routing settings -----------------------------------------------

echo "[Step 12] Routing settings"
resp=$(call GET /api/routing/settings)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  fit=$(echo "$HTTP_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'fit={d[\"fit_weight\"]}, cost={d[\"cost_weight\"]}')" 2>/dev/null || echo "?")
  pass "GET /api/routing/settings -> 200 ($fit)"
else
  fail "GET /api/routing/settings -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# =============================================================================
# Phase 10 — Benchmark Lifecycle (Steps 13-21)
# =============================================================================
# These steps test the full benchmark lifecycle: engines, collections,
# benchmark execution, storage probes, and cascade delete.
# They require running DuckDB workers for the benchmark to succeed.
# =============================================================================

# --- Step 13: List engines ---------------------------------------------------

echo "[Step 13] List engines"
resp=$(call GET /api/engines)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  ENGINE_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  ENGINE_IDS=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(','.join(e['id'] for e in json.load(sys.stdin)))" 2>/dev/null || echo "")
  pass "GET /api/engines -> 200 ($ENGINE_COUNT engines: $ENGINE_IDS)"
else
  fail "GET /api/engines -> $HTTP_STATUS" "$HTTP_BODY"
  ENGINE_IDS=""
fi
echo

# --- Step 14: Create collection ----------------------------------------------

COLLECTION_ID=""
echo "[Step 14] Create collection"
resp=$(call POST /api/collections '{"name":"Smoke Test Collection","description":"Created by smoke-test.sh"}')
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "201" ]]; then
  COLLECTION_ID=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
  if [[ -n "$COLLECTION_ID" ]]; then
    pass "POST /api/collections -> 201 (id=$COLLECTION_ID)"
  else
    fail "POST /api/collections -> 201 but no id in body" "$HTTP_BODY"
  fi
else
  fail "POST /api/collections -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 15: Add queries to collection --------------------------------------

echo "[Step 15] Add queries to collection"
if [[ -n "$COLLECTION_ID" ]]; then
  resp=$(call POST "/api/collections/${COLLECTION_ID}/queries" '{"sql":"SELECT 1 AS benchmark_q1","name":"Q1 - trivial"}')
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "201" ]]; then
    pass "POST query 1 -> 201"
  else
    fail "POST query 1 -> $HTTP_STATUS" "$HTTP_BODY"
  fi

  resp=$(call POST "/api/collections/${COLLECTION_ID}/queries" '{"sql":"SELECT 2 AS benchmark_q2","name":"Q2 - trivial"}')
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "201" ]]; then
    pass "POST query 2 -> 201"
  else
    fail "POST query 2 -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No collection ID — skipping add queries"
fi
echo

# --- Step 16: Run benchmark --------------------------------------------------

BENCHMARK_ID=""
echo "[Step 16] Run benchmark"
if [[ -n "$COLLECTION_ID" && -n "$ENGINE_IDS" ]]; then
  # Build engine_ids JSON array from comma-separated list
  ENGINE_JSON=$(echo "$ENGINE_IDS" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip().split(',')))" 2>/dev/null || echo '[]')
  resp=$(call POST /api/benchmarks "{\"collection_id\":$COLLECTION_ID,\"engine_ids\":$ENGINE_JSON,\"warmup_runs\":1}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "201" ]]; then
    BENCHMARK_ID=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
    BM_STATUS=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
    if [[ -n "$BENCHMARK_ID" ]]; then
      pass "POST /api/benchmarks -> $HTTP_STATUS (id=$BENCHMARK_ID, status=$BM_STATUS)"
    else
      fail "POST /api/benchmarks -> $HTTP_STATUS but no id" "$HTTP_BODY"
    fi
  else
    fail "POST /api/benchmarks -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No collection or engines — skipping benchmark run"
fi
echo

# --- Step 17: Get benchmark detail -------------------------------------------

echo "[Step 17] Get benchmark detail"
if [[ -n "$BENCHMARK_ID" ]]; then
  resp=$(call GET "/api/benchmarks/${BENCHMARK_ID}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    WARMUP_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('warmups',[])))" 2>/dev/null || echo "0")
    RESULT_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo "0")
    pass "GET /api/benchmarks/$BENCHMARK_ID -> 200 ($WARMUP_COUNT warmups, $RESULT_COUNT results)"
  else
    fail "GET /api/benchmarks/$BENCHMARK_ID -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No benchmark ID — skipping detail check"
fi
echo

# --- Step 18: List benchmarks for collection ---------------------------------

echo "[Step 18] List benchmarks for collection"
if [[ -n "$COLLECTION_ID" ]]; then
  resp=$(call GET "/api/benchmarks?collection_id=${COLLECTION_ID}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    BM_LIST_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    pass "GET /api/benchmarks?collection_id=$COLLECTION_ID -> 200 ($BM_LIST_COUNT benchmarks)"
  else
    fail "GET /api/benchmarks?collection_id=$COLLECTION_ID -> $HTTP_STATUS" "$HTTP_BODY"
  fi
else
  skip "No collection ID — skipping benchmark list"
fi
echo

# --- Step 19: Run storage probes ---------------------------------------------

echo "[Step 19] Run storage probes"
resp=$(call POST /api/latency-probes/run)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  PROBE_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  pass "POST /api/latency-probes/run -> 200 ($PROBE_COUNT probes)"
else
  fail "POST /api/latency-probes/run -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 20: List storage probes --------------------------------------------

echo "[Step 20] List storage probes"
resp=$(call GET /api/latency-probes)
parse_resp "$resp"
if [[ "$HTTP_STATUS" == "200" ]]; then
  PROBE_LIST_COUNT=$(echo "$HTTP_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  pass "GET /api/latency-probes -> 200 ($PROBE_LIST_COUNT probes)"
else
  fail "GET /api/latency-probes -> $HTTP_STATUS" "$HTTP_BODY"
fi
echo

# --- Step 21: Delete collection + verify cascade -----------------------------

echo "[Step 21] Delete collection (cascade)"
if [[ -n "$COLLECTION_ID" ]]; then
  resp=$(call DELETE "/api/collections/${COLLECTION_ID}")
  parse_resp "$resp"
  if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "204" ]]; then
    pass "DELETE /api/collections/$COLLECTION_ID -> $HTTP_STATUS"
  else
    fail "DELETE /api/collections/$COLLECTION_ID -> $HTTP_STATUS" "$HTTP_BODY"
  fi

  # Verify cascade: benchmark should be gone
  if [[ -n "$BENCHMARK_ID" ]]; then
    resp=$(call GET "/api/benchmarks/${BENCHMARK_ID}")
    parse_resp "$resp"
    if [[ "$HTTP_STATUS" == "404" ]]; then
      pass "GET /api/benchmarks/$BENCHMARK_ID -> 404 (cascade confirmed)"
    else
      fail "GET /api/benchmarks/$BENCHMARK_ID -> $HTTP_STATUS (expected 404 after cascade)" "$HTTP_BODY"
    fi
  fi
else
  skip "No collection ID — skipping delete + cascade check"
fi
echo

# --- Summary ----------------------------------------------------------------

echo "============================================"
echo " Results: $PASS PASSED, $SKIP SKIPPED, $FAIL FAILED  (of $TOTAL)"
echo "============================================"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
