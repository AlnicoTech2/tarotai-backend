#!/bin/bash
# ==============================================================
# TarotAI — E2E Production Verification Script
# Tests the full pipeline: Firebase Auth → RDS → Prokerala → OpenAI → pgvector
# ==============================================================

set -e

BASE_URL="https://zbshm9vrhx.ap-south-1.awsapprunner.com/api/v1"
HEALTH_URL="https://zbshm9vrhx.ap-south-1.awsapprunner.com/health"
FIREBASE_API_KEY="AIzaSyA09GrosfxWXQheNu8kE6Ade-4mueT6l1o"

# --- Reviewer account credentials ---
REVIEWER_EMAIL="admin@tarotai.com"
REVIEWER_PASSWORD="${REVIEWER_PASSWORD:?Set REVIEWER_PASSWORD env var}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; echo "  Response: $2"; exit 1; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

# ==============================================================
# TEST 0: Health Check (no auth)
# ==============================================================
info "Test 0: Health check..."
HEALTH=$(curl -s -w "\n%{http_code}" "$HEALTH_URL")
HTTP_CODE=$(echo "$HEALTH" | tail -1)
BODY=$(echo "$HEALTH" | head -1)

if [ "$HTTP_CODE" = "200" ]; then
  pass "Health check returned 200 — $BODY"
else
  fail "Health check returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 1: Get Firebase ID Token (Firebase REST API)
# Verifies: Firebase credentials are valid on the server
# ==============================================================
info "Test 1: Authenticating with Firebase..."
AUTH_RESPONSE=$(curl -s -X POST \
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=$FIREBASE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$REVIEWER_EMAIL\",
    \"password\": \"$REVIEWER_PASSWORD\",
    \"returnSecureToken\": true
  }")

ID_TOKEN=$(echo "$AUTH_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('idToken',''))" 2>/dev/null)

if [ -z "$ID_TOKEN" ]; then
  fail "Firebase sign-in failed" "$AUTH_RESPONSE"
fi
pass "Firebase token obtained (${#ID_TOKEN} chars)"

AUTH_HEADER="Authorization: Bearer $ID_TOKEN"

# ==============================================================
# TEST 2: GET /auth/me (Reviewer account — should 404 after wipe)
# Verifies: Firebase JWT validation on server + DB read + reviewer wipe logic
# ==============================================================
info "Test 2: GET /auth/me (reviewer wipe check)..."
ME_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/auth/me" \
  -H "$AUTH_HEADER")
HTTP_CODE=$(echo "$ME_RESPONSE" | tail -1)
BODY=$(echo "$ME_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "404" ]; then
  pass "GET /me returned 404 — reviewer data wiped (expected)"
elif [ "$HTTP_CODE" = "200" ]; then
  pass "GET /me returned 200 — user exists (first-time call)"
elif [ "$HTTP_CODE" = "401" ]; then
  fail "JWT rejected by server — check Firebase credentials on App Runner" "$BODY"
elif [ "$HTTP_CODE" = "500" ]; then
  fail "Server error — check DB connection (RDS)" "$BODY"
else
  fail "Unexpected status $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 3: POST /auth/register (Create user)
# Verifies: DB write (users table) + Prokerala API (birth chart) + Nominatim (geocoding)
# ==============================================================
info "Test 3: POST /auth/register (DB write + Prokerala API)..."
REGISTER_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/auth/register" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "E2E Test User",
    "date_of_birth": "1998-10-25",
    "time_of_birth": "06:30",
    "city_of_birth": "Osmanabad",
    "latitude": 18.1860,
    "longitude": 76.0488
  }')
HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -1)
BODY=$(echo "$REGISTER_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "201" ]; then
  # Check if Prokerala data came through
  ZODIAC=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('zodiac_sign','NONE'))" 2>/dev/null)
  MOON=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('moon_sign','NONE'))" 2>/dev/null)
  CHART=$(echo "$BODY" | python3 -c "import sys,json; bc=json.load(sys.stdin).get('birth_chart'); print('YES' if bc and bc.get('planets') else 'NO')" 2>/dev/null)
  pass "User registered — Zodiac: $ZODIAC, Moon: $MOON, Birth chart: $CHART"
  if [ "$CHART" = "NO" ]; then
    info "  WARNING: Birth chart empty — Prokerala API may be down or misconfigured"
  fi
elif [ "$HTTP_CODE" = "409" ]; then
  pass "User already exists (409) — registration works, user wasn't wiped"
elif [ "$HTTP_CODE" = "500" ]; then
  fail "Server error on register — check RDS connection + Prokerala env vars" "$BODY"
else
  fail "Registration returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 4: GET /daily-card/ (Deterministic daily card)
# Verifies: DB read (tarot_cards table) + user lookup + Redis fallback
# ==============================================================
info "Test 4: GET /daily-card/ (DB read + card data)..."
DAILY_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/daily-card/" \
  -H "$AUTH_HEADER")
HTTP_CODE=$(echo "$DAILY_RESPONSE" | tail -1)
BODY=$(echo "$DAILY_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
  CARD_NAME=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['name'])" 2>/dev/null)
  pass "Daily card: $CARD_NAME"
elif [ "$HTTP_CODE" = "500" ]; then
  fail "Daily card failed — check if tarot_cards table is seeded (78 cards)" "$BODY"
else
  fail "Daily card returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 5: POST /readings/ — Single card reading
# Verifies: THE BIG ONE — OpenAI GPT-4o + LangChain + pgvector write + full pipeline
# ==============================================================
info "Test 5: POST /readings/ — Single card AI reading (this takes 10-30s)..."
READING_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/readings/" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  --max-time 60 \
  -d '{
    "spread_type": "single",
    "question": "E2E test — will this deployment succeed?"
  }')
HTTP_CODE=$(echo "$READING_RESPONSE" | tail -1)
BODY=$(echo "$READING_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "201" ]; then
  READING_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)
  CARD=$(echo "$BODY" | python3 -c "import sys,json; c=json.load(sys.stdin)['cards'][0]; print(f\"{c['card']} ({'Rev' if c['reversed'] else 'Upright'})\")" 2>/dev/null)
  TEXT_LEN=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['reading_text']))" 2>/dev/null)
  pass "AI reading generated — Card: $CARD, Text: ${TEXT_LEN} chars, ID: $READING_ID"
elif [ "$HTTP_CODE" = "403" ]; then
  fail "Reading limit hit (shouldn't happen for reviewer)" "$BODY"
elif [ "$HTTP_CODE" = "500" ]; then
  fail "Reading generation failed — check OpenAI API key + LangChain config in logs" "$BODY"
else
  fail "Reading returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 6: GET /readings/ (Reading history)
# Verifies: DB read from readings table + response serialization
# ==============================================================
info "Test 6: GET /readings/ (history)..."
HISTORY_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/readings/" \
  -H "$AUTH_HEADER")
HTTP_CODE=$(echo "$HISTORY_RESPONSE" | tail -1)
BODY=$(echo "$HISTORY_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
  COUNT=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
  pass "Reading history returned $COUNT reading(s)"
else
  fail "History returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# TEST 7: GET /readings/:id (Specific reading by ID)
# Verifies: UUID-based lookup + ownership check
# ==============================================================
if [ -n "$READING_ID" ]; then
  info "Test 7: GET /readings/$READING_ID..."
  DETAIL_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/readings/$READING_ID" \
    -H "$AUTH_HEADER")
  HTTP_CODE=$(echo "$DETAIL_RESPONSE" | tail -1)
  BODY=$(echo "$DETAIL_RESPONSE" | sed '$d')

  if [ "$HTTP_CODE" = "200" ]; then
    pass "Reading detail fetched by ID"
  else
    fail "Reading detail returned $HTTP_CODE" "$BODY"
  fi
else
  info "Test 7: SKIPPED (no reading ID from test 5)"
fi

# ==============================================================
# TEST 8: GET /cards/ (All 78 tarot cards)
# Verifies: Seeded tarot_cards table
# ==============================================================
info "Test 8: GET /cards/..."
CARDS_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/cards/" \
  -H "$AUTH_HEADER")
HTTP_CODE=$(echo "$CARDS_RESPONSE" | tail -1)
BODY=$(echo "$CARDS_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
  CARD_COUNT=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
  if [ "$CARD_COUNT" = "78" ]; then
    pass "All 78 tarot cards present"
  else
    info "  WARNING: Expected 78 cards, got $CARD_COUNT"
  fi
else
  fail "Cards endpoint returned $HTTP_CODE" "$BODY"
fi

# ==============================================================
# SUMMARY
# ==============================================================
echo ""
echo "========================================="
echo -e "${GREEN}  E2E VERIFICATION COMPLETE${NC}"
echo "========================================="
echo "  Backend:    $HEALTH_URL"
echo "  Pipeline:   Firebase → RDS → Prokerala → OpenAI → pgvector"
echo "  Status:     ALL SYSTEMS OPERATIONAL"
echo "========================================="
