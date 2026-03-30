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

# --- Summary ----------------------------------------------------------------

echo "============================================"
echo " Results: $PASS PASSED, $SKIP SKIPPED, $FAIL FAILED  (of $TOTAL)"
echo "============================================"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
