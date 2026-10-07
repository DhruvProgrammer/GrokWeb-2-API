#!/usr/bin/env bash
#
# test-api.sh - quick smoke test against a running grok-web-to-api.
# Usage:  ./test-api.sh [host:port]
# Default host:port is localhost:9421

set -uo pipefail

HOST="${1:-localhost:9421}"
BASE="http://${HOST}"
PASS=0
FAIL=0

if [ -t 1 ]; then
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'
else
    GREEN=""; RED=""; YELLOW=""; RESET=""
fi

ok()   { echo "${GREEN}PASS${RESET}  $1"; PASS=$((PASS+1)); }
bad()  { echo "${RED}FAIL${RESET}  $1"; FAIL=$((FAIL+1)); }
note() { echo "${YELLOW}NOTE${RESET}  $1"; }

echo "Running smoke tests against ${BASE}..."
echo

# 1. health endpoint returns 200 or 503 (not 5xx)
HSTATUS=$(curl -s -o /tmp/h.body -w '%{http_code}' "$BASE/health" || echo 000)
if [ "$HSTATUS" = "200" ] || [ "$HSTATUS" = "503" ]; then
    ok "health returns expected status ($HSTATUS)"
else
    bad "health returned $HSTATUS"
fi

# 2. root returns 200 with name field
ROOT=$(curl -s "$BASE/" || echo "")
if echo "$ROOT" | grep -q '"name":"grok-web-to-api"'; then
    ok "root returns server identity"
else
    bad "root missing identity: $ROOT"
fi

# 3. /v1/models returns 200 with model list
MODELS=$(curl -s -o /tmp/m.body -w '%{http_code}' "$BASE/v1/models" || echo 000)
if [ "$MODELS" = "200" ] && grep -q '"object":"list"' /tmp/m.body && grep -q '"grok-auto"' /tmp/m.body; then
    ok "/v1/models returns valid list"
else
    bad "/v1/models broken: status=$MODELS body=$(cat /tmp/m.body | head -c 200)"
fi

# 4. /v1/models/:id returns one model
ONE=$(curl -s -o /tmp/o.body -w '%{http_code}' "$BASE/v1/models/grok-4" || echo 000)
if [ "$ONE" = "200" ] && grep -q '"id":"grok-4"' /tmp/o.body; then
    ok "/v1/models/:id works"
else
    bad "/v1/models/grok-4 broken: status=$ONE"
fi

# 5. missing model field returns 400 or 422
RESP=$(curl -s -o /tmp/e1.body -w '%{http_code}' -X POST "$BASE/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d '{"messages":[{"role":"user","content":"hi"}]}' || echo 000)
if [ "$RESP" = "400" ] || [ "$RESP" = "422" ]; then
    ok "missing model returns $RESP"
else
    bad "missing model returned $RESP (want 400 or 422)"
fi

# 6. unknown model returns 400
RESP=$(curl -s -o /tmp/e2.body -w '%{http_code}' -X POST "$BASE/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d '{"model":"does-not-exist","messages":[{"role":"user","content":"hi"}]}' || echo 000)
if [ "$RESP" = "400" ]; then
    ok "unknown model returns 400"
else
    bad "unknown model returned $RESP (want 400)"
fi

# 7. empty messages returns 400
RESP=$(curl -s -o /tmp/e3.body -w '%{http_code}' -X POST "$BASE/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d '{"model":"grok-auto","messages":[]}' || echo 000)
if [ "$RESP" = "400" ]; then
    ok "empty messages returns 400"
else
    bad "empty messages returned $RESP (want 400)"
fi

# 8. malformed JSON returns 400 or 422
RESP=$(curl -s -o /tmp/e4.body -w '%{http_code}' -X POST "$BASE/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d '{not json' || echo 000)
if [ "$RESP" = "400" ] || [ "$RESP" = "422" ]; then
    ok "malformed JSON returns 400/422"
else
    bad "malformed JSON returned $RESP"
fi

# 9. legacy /v1/completions with valid prompt reaches the handler
RESP=$(curl -s -o /tmp/lc.body -w '%{http_code}' -X POST "$BASE/v1/completions" \
    -H 'content-type: application/json' \
    -d '{"model":"grok-auto","prompt":"hi"}' || echo 000)
if [ "$RESP" = "200" ] || [ "$RESP" = "502" ] || [ "$RESP" = "503" ]; then
    ok "legacy /v1/completions reachable"
else
    bad "/v1/completions returned $RESP"
fi

# 10. CORS preflight returns 204 or 200
RESP=$(curl -s -o /dev/null -w '%{http_code}' -X OPTIONS "$BASE/v1/chat/completions" \
    -H 'origin: http://example.com' \
    -H 'access-control-request-method: POST' || echo 000)
if [ "$RESP" = "204" ] || [ "$RESP" = "200" ]; then
    ok "CORS preflight succeeds ($RESP)"
else
    bad "CORS preflight returned $RESP"
fi

# 11. streaming endpoint emits text/event-stream
HDRS=$(curl -s -i -X POST "$BASE/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d '{"model":"grok-auto","stream":true,"messages":[{"role":"user","content":"hi"}]}' \
    --max-time 90 2>&1 || true)
if echo "$HDRS" | grep -qi 'content-type: text/event-stream'; then
    ok "streaming returns text/event-stream"
else
    note "streaming content-type not seen (server may be in degraded auth state - that is OK in CI)"
fi

echo
echo "Summary: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1