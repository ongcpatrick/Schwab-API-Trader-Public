#!/usr/bin/env bash
# Schwab API Trader server wrapper.
# All data and execution calls go through the running FastAPI server.
# Usage: bash scripts/schwab_server.sh <subcommand> [args...]
#
# The server handles all Schwab OAuth complexity.
# Routines never call Schwab directly — they call this wrapper.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

# Load .env for local runs (cloud routines use process env vars instead)
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

SERVER="${SERVER_URL:-${SCHWAB_TRADER_DASHBOARD_URL:-http://localhost:8000}}"

# Verify server is reachable before any call
_check_server() {
    if ! curl -fsS --max-time 5 "$SERVER/health" > /dev/null 2>&1; then
        echo "ERROR: Server not reachable at $SERVER" >&2
        echo "Start the server with: ./start.sh" >&2
        exit 2
    fi
}

cmd="${1:-}"
shift || true

case "$cmd" in
    # ── Portfolio / account ─────────────────────────────────────────────────
    accounts)
        _check_server
        curl -fsS "$SERVER/api/v1/schwab/accounts"
        ;;

    positions)
        # Returns positions embedded in the accounts response
        _check_server
        curl -fsS "$SERVER/api/v1/schwab/accounts" | python3 -c "
import json, sys
data = json.load(sys.stdin)
accounts = data if isinstance(data, list) else [data]
for acct in accounts:
    positions = acct.get('securitiesAccount', {}).get('positions', [])
    print(json.dumps(positions, indent=2))
"
        ;;

    quotes)
        # Usage: quotes AAPL NVDA AMD ...
        _check_server
        symbols="${*:?usage: quotes SYM1 SYM2 ...}"
        sym_param=$(echo "$symbols" | tr ' ' ',')
        curl -fsS "$SERVER/api/v1/schwab/quotes?symbols=$sym_param"
        ;;

    orders)
        _check_server
        curl -fsS "$SERVER/api/v1/schwab/orders"
        ;;

    # ── Research ─────────────────────────────────────────────────────────────
    news)
        # Usage: news AAPL NVDA  (space-separated symbols, optional)
        _check_server
        if [[ $# -gt 0 ]]; then
            sym_param=$(echo "$*" | tr ' ' ',')
            curl -fsS "$SERVER/api/v1/news/feed?symbols=$sym_param"
        else
            curl -fsS "$SERVER/api/v1/news/feed"
        fi
        ;;

    earnings)
        _check_server
        curl -fsS "$SERVER/api/v1/earnings/calendar"
        ;;

    sectors)
        # Usage: sectors [SYM1 SYM2 ...]  (defaults to major sector ETFs)
        _check_server
        if [[ $# -gt 0 ]]; then
            sym_param=$(echo "$*" | tr ' ' ',')
        else
            sym_param="XLK,XLF,XLE,XLV,XLI,XLY,XLP,XLU,XLB,XLRE,XLC"
        fi
        curl -fsS "$SERVER/api/v1/earnings/sectors?symbols=$sym_param"
        ;;

    # ── Performance ──────────────────────────────────────────────────────────
    performance)
        _check_server
        curl -fsS "$SERVER/api/v1/performance/history?days=${1:-30}"
        ;;

    # ── Agent actions ────────────────────────────────────────────────────────
    run-check)
        # Trigger the portfolio health check (flags down positions, earnings risk, etc.)
        _check_server
        curl -fsS -X POST "$SERVER/api/v1/agent/run-check" \
            -H "Content-Type: application/json"
        ;;

    run-buy-scan)
        # Trigger the buy scan — screens watchlist, calls Claude, sends SMS/email proposals
        _check_server
        curl -fsS -X POST "$SERVER/api/v1/agent/run-buy-scan" \
            -H "Content-Type: application/json"
        ;;

    alerts)
        # List all stored alerts/proposals
        _check_server
        curl -fsS "$SERVER/api/v1/agent/alerts"
        ;;

    notify)
        # Usage: notify "message"  OR  notify urgent "message"
        # Routes SMS through the server — no Twilio creds needed in routine env
        _check_server
        URGENT="false"
        if [[ "${1:-}" == "urgent" ]]; then
            URGENT="true"
            shift
        fi
        MSG="${*:?usage: notify [urgent] <message>}"
        curl -fsS -X POST "$SERVER/api/v1/agent/notify" \
            -H "Content-Type: application/json" \
            -d "{\"message\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MSG"), \"urgent\": $URGENT}"
        ;;

    # ── Health ───────────────────────────────────────────────────────────────
    health)
        curl -fsS "$SERVER/health"
        ;;

    ping)
        if curl -fsS --max-time 5 "$SERVER/health" > /dev/null 2>&1; then
            echo "Server is up at $SERVER"
        else
            echo "Server is DOWN at $SERVER" >&2
            exit 2
        fi
        ;;

    *)
        cat >&2 <<EOF
Usage: bash scripts/schwab_server.sh <subcommand> [args]

Subcommands:
  accounts              Full account + positions data
  positions             Positions only (parsed from accounts)
  quotes SYM1 SYM2...   Live quotes for one or more symbols
  orders                Open orders
  news [SYM1 SYM2...]   News feed (optionally filtered by symbols)
  earnings              Upcoming earnings calendar
  sectors               Sector performance data
  performance [days]    Performance history (default 30 days)
  run-check             Trigger portfolio health check agent
  run-buy-scan          Trigger buy scan agent (screens + proposes)
  alerts                List all stored alerts and proposals
  health                Raw health check response
  ping                  Human-readable server status check
EOF
        exit 1
        ;;
esac
echo
