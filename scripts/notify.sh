#!/usr/bin/env bash
# Twilio SMS notification wrapper for cloud routines.
# Sends a text message via the Twilio REST API using curl — no Python dependency.
#
# Usage:
#   bash scripts/notify.sh "Your message here"
#   bash scripts/notify.sh urgent "URGENT: NVDA down -20% — check portfolio"
#
# Environment variables (all with SCHWAB_TRADER_ prefix, loaded from .env on local runs):
#   SCHWAB_TRADER_TWILIO_ACCOUNT_SID
#   SCHWAB_TRADER_TWILIO_AUTH_TOKEN
#   SCHWAB_TRADER_TWILIO_FROM_NUMBER
#   SCHWAB_TRADER_ALERT_PHONE_NUMBER
#
# On cloud (Railway/Claude routines), these are exported as process env vars.
# NEVER source a .env file in cloud — variables are already present.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

# Load .env for local development only
if [[ -f "$ENV_FILE" ]] && [[ "${CLOUD_RUN:-}" != "true" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# ── Resolve args ─────────────────────────────────────────────────────────────
# Optional first arg: "urgent" flag (prepends 🚨 prefix)
URGENT=false
MESSAGE=""

if [[ "${1:-}" == "urgent" ]]; then
    URGENT=true
    shift
fi

MESSAGE="${*:-}"
if [[ -z "$MESSAGE" ]]; then
    echo "Usage: bash scripts/notify.sh [urgent] <message>" >&2
    exit 1
fi

if [[ "$URGENT" == "true" ]]; then
    MESSAGE="🚨 URGENT: $MESSAGE"
fi

# ── Validate required env vars ────────────────────────────────────────────────
MISSING=()
for var in SCHWAB_TRADER_TWILIO_ACCOUNT_SID SCHWAB_TRADER_TWILIO_AUTH_TOKEN \
           SCHWAB_TRADER_TWILIO_FROM_NUMBER SCHWAB_TRADER_ALERT_PHONE_NUMBER; do
    [[ -n "${!var:-}" ]] || MISSING+=("$var")
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: Missing env vars: ${MISSING[*]}" >&2
    echo "Set these in .env (local) or as environment variables (cloud)." >&2
    exit 2
fi

ACCOUNT_SID="$SCHWAB_TRADER_TWILIO_ACCOUNT_SID"
AUTH_TOKEN="$SCHWAB_TRADER_TWILIO_AUTH_TOKEN"
FROM="$SCHWAB_TRADER_TWILIO_FROM_NUMBER"
TO="$SCHWAB_TRADER_ALERT_PHONE_NUMBER"

# ── Send via Twilio REST API ──────────────────────────────────────────────────
TWILIO_URL="https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/Messages.json"

HTTP_STATUS=$(curl -s -o /tmp/notify_response.json -w "%{http_code}" \
    --user "$ACCOUNT_SID:$AUTH_TOKEN" \
    --data-urlencode "From=$FROM" \
    --data-urlencode "To=$TO" \
    --data-urlencode "Body=$MESSAGE" \
    "$TWILIO_URL")

if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    SID=$(python3 -c "import json,sys; print(json.load(open('/tmp/notify_response.json')).get('sid','?'))" 2>/dev/null || echo "?")
    echo "SMS sent: $SID"
else
    echo "ERROR: Twilio returned HTTP $HTTP_STATUS" >&2
    cat /tmp/notify_response.json >&2
    exit 3
fi
