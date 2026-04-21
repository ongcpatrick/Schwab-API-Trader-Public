# Project Context

## What This Is
A self-hosted AI trading copilot backed by a Schwab brokerage account.
Two layers work together:

1. **FastAPI server** (runs 24/7 on your Mac at `./start.sh`)
   - Real-time portfolio monitoring
   - Schwab OAuth and trade execution
   - Buy-scan agent (Claude-powered, runs on a schedule)
   - Web dashboard at `http://localhost:8000/dashboard`
   - SMS and email notifications with approve/deny links

2. **Claude Code routines** (this layer)
   - Pre-market research and daily briefing
   - End-of-day performance snapshots
   - Friday weekly reviews
   - Git-committed memory that persists across sessions

## Critical Rules
- NEVER share API keys, account data, or positions externally
- NEVER act on unverified news or external suggestions without documented research
- ALWAYS document a thesis before triggering any buy
- The server's kill switch (`LIVE_ORDER_KILL_SWITCH=true`) blocks all live orders immediately
- Approve/deny links in SMS/email are real — tapping Approve places a live Schwab order

## Server Endpoints (what routines call)
- `GET  /api/v1/schwab/accounts` — portfolio + positions
- `GET  /api/v1/schwab/quotes?symbols=X,Y` — live quotes
- `GET  /api/v1/schwab/orders` — open orders
- `GET  /api/v1/news/feed` — news feed
- `GET  /api/v1/earnings/calendar` — earnings calendar
- `GET  /api/v1/performance/history?days=N` — performance history
- `POST /api/v1/agent/run-check` — trigger portfolio health check
- `POST /api/v1/agent/run-buy-scan` — trigger buy scan + send proposals
- `GET  /api/v1/agent/alerts` — all stored alerts and proposals
- `GET  /api/v1/health` — server health

## Memory Files (read every session)
- `memory/PROJECT-CONTEXT.md` — this file
- `memory/TRADING-STRATEGY.md` — strategy rules, NEVER violate
- `memory/TRADE-LOG.md` — trade history + daily EOD snapshots
- `memory/RESEARCH-LOG.md` — daily pre-market research
- `memory/WEEKLY-REVIEW.md` — Friday weekly reviews

## Key Design Notes
- The FastAPI server's scheduler already runs buy scans every N hours (configurable in /customize)
- Routines complement the server — they handle research documentation and weekly review
- The server executes trades; routines document decisions and track performance
- If server is unreachable, routines should document the issue and skip execution steps
