# Schwab API Trader — CLAUDE.md

## Project Overview
A personal AI-powered portfolio management dashboard built on the Schwab API. Single-user, self-hosted FastAPI app. All UI is server-rendered HTML/CSS/JS returned from route handlers — no build step, no bundler.

## Starting the Server
```bash
./start.sh
# or manually:
PYTHONPATH=src .venv/bin/python3.13 -m uvicorn schwab_trader.server.app:app --host 0.0.0.0 --port 8000 --reload
```
- Dashboard: `http://localhost:8000/` (redirects to `/dashboard`)
- Settings: `http://localhost:8000/customize`
- Setup/Auth: `http://localhost:8000/` (first run, before redirect kicks in after auth)

## Architecture
```
src/schwab_trader/
├── server/
│   ├── app.py              — FastAPI app factory, lifespan, scheduler loop
│   └── routes/
│       ├── home.py         — ALL dashboard HTML (~4600 lines): _live_dashboard_html(), _customize_html(), _home_html()
│       ├── agent.py        — Agent routes: run-check, run-buy-scan, proposals/execute, place-sell-order
│       ├── schwab.py       — Schwab pass-through: /accounts, /quotes, /orders
│       ├── advisor.py      — Claude streaming chat endpoint
│       ├── earnings.py     — Earnings calendar + sector data
│       ├── news.py         — News feed
│       └── performance.py  — Portfolio performance tracking
├── agent/
│   ├── service.py          — AgentService: run_check(), run_buy_scan()
│   ├── store.py            — AlertStore (flat JSON .alerts.json)
│   ├── tools.py            — ToolExecutor: Claude tool implementations
│   └── monitor.py          — Background portfolio monitor
├── broker/service.py       — SchwabBrokerService (wraps SchwabClient)
├── schwab/client.py        — Raw Schwab REST API client
├── execution/service.py    — ExecutionService: risk checks → preview → place_order
├── advisor/service.py      — AdvisorService: streaming Claude chat
├── screening/service.py    — Stock screener (watchlist + scoring)
├── notifications/
│   ├── sms.py              — Twilio SMS alerts
│   └── email.py            — SMTP email with approve/deny buttons
├── core/settings.py        — Pydantic settings (env prefix SCHWAB_TRADER_)
└── auth/                   — OAuth token management
```

## Key Design Decisions
- **Single HTML file per page**: All dashboard HTML/CSS/JS lives inside `_live_dashboard_html()` in `home.py`. No templates, no static files.
- **CSS design tokens**: `:root` variables at top of `_live_dashboard_html()`. Current palette: `--bg:#080B10`, `--surface:#0E1318`, `--accent:#2563EB`, `--green:#22C55E`, `--red:#EF4444`.
- **Icons**: Lucide JS CDN (vanilla, not React). `<script src="https://unpkg.com/lucide@0.447.0/dist/umd/lucide.min.js">`. Call `lucide.createIcons()` after DOM load. No emojis in the dashboard.
- **JS**: Vanilla JS only. `apiFetch()` wraps fetch. `positions` global holds live portfolio data. `showPage(name)` handles SPA navigation.
- **Settings**: Pydantic `Settings` with `env_prefix=SCHWAB_TRADER_`. Written to `.env` via `update_settings`. Always call `get_settings.cache_clear()` after writing.
- **Proposal flow**: Agent proposes → stored in `.alerts.json` → user approves → `ExecutionService.execute_proposal()` → risk check → Schwab preview → `place_order()`.
- **Sell flow**: User clicks Sell in portfolio table → sell modal with tax calculator → `POST /api/v1/agent/place-sell-order` → same `ExecutionService` path.

## Environment Variables (`.env`)
All prefixed with `SCHWAB_TRADER_`:
- `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL`
- `ANTHROPIC_API_KEY`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `ALERT_PHONE_NUMBER`
- `DASHBOARD_URL` — base URL for SMS approve/deny links
- `BUY_SCAN_BUDGET`, `BUY_SCAN_INTERVAL_HOURS`, `BUY_SCAN_MAX_PROPOSALS`
- `LIVE_ORDER_KILL_SWITCH` — set to `true` to block all live orders
- `LIVE_ORDER_MAX_DAILY_LOSS_DOLLARS`, `LIVE_ORDER_MAX_ORDER_NOTIONAL_DOLLARS`

## Common Tasks

### Edit the dashboard UI
Edit `src/schwab_trader/server/routes/home.py`. The `_live_dashboard_html()` function starts at line ~1145. CSS is inline in `<style>` tag. JS is inline before `</body>`.

### Add a new API endpoint
Add to the appropriate route file in `server/routes/`. Register in `server/app.py` if creating a new router.

### Run tests
```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
```

### Check server logs
```bash
tail -f /tmp/schwab_server.log
```

## Cloud Bot Architecture

The server can run on Railway (always-on) so Claude Code cloud routines can call it 24/7.

```
Claude Code cloud routines (scheduled, stateless)
    └─ scripts/schwab_server.sh <subcommand>    ← calls FastAPI server
            └─ FastAPI server on Railway         ← handles Schwab OAuth
                    └─ Schwab API               ← real broker

Memory persistence: routines commit memory/*.md to git after each run.
```

### Cloud Bot Files
- `scripts/schwab_server.sh` — bash wrapper for all server API calls
- `scripts/notify.sh` — Twilio SMS via curl (no Python needed in routines)
- `routines/pre-market.md` — 8 AM ET: research + account snapshot
- `routines/market-open.md` — 9:45 AM ET: validate buys, trigger buy scan
- `routines/midday.md` — 12 PM ET: thesis check, news scan
- `routines/daily-summary.md` — 4:15 PM ET: EOD snapshot + P&L commit
- `routines/weekly-review.md` — Friday 4 PM ET: full week review
- `memory/TRADING-STRATEGY.md` — rules the agent must follow
- `memory/TRADE-LOG.md` — append-only daily EOD snapshots
- `memory/RESEARCH-LOG.md` — append-only per-day research entries
- `routines/README.md` — setup instructions for Railway + Claude Code cloud

### Railway Deployment
```bash
# 1. Push repo to GitHub (make it private first)
# 2. Deploy on Railway → New Project → Deploy from GitHub repo
# 3. Set these environment variables in Railway:
#    SCHWAB_TRADER_SCHWAB_APP_KEY=...
#    SCHWAB_TRADER_SCHWAB_APP_SECRET=...
#    SCHWAB_TRADER_SCHWAB_CALLBACK_URL=https://your-app.railway.app/auth/callback
#    SCHWAB_TRADER_ANTHROPIC_API_KEY=...
#    SCHWAB_TRADER_TWILIO_ACCOUNT_SID=...  (and other Twilio vars)
#    SCHWAB_TOKEN_JSON=<contents of .data/schwab-token.json>  ← token bootstrap
# 4. In cloud routines: set SERVER_URL=https://your-app.railway.app
```

### Direct Order Endpoint (for autonomous bot)
`POST /api/v1/agent/direct-order` — places an order without the proposal/approval flow.
Still runs the full ExecutionService path: kill switch → risk checks → preview → place.
Requires a non-empty `reasoning` field (document the thesis).

## What NOT to Do
- Do not use React, Vue, or any frontend framework — this is intentionally vanilla JS
- Do not add emojis to the dashboard — use Lucide SVG icons only
- Do not import `get_settings()` without calling `.cache_clear()` after writing `.env`
- Do not call `place_order()` directly — always go through `ExecutionService` for risk checks
- Do not source `.env` in cloud routines — env vars are already in the process environment
