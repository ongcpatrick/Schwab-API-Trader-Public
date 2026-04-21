# Schwab AI Trader

A self-hosted, AI-powered portfolio management dashboard built on the **Charles Schwab brokerage API** and **Claude**. Runs entirely on your own machine — your data never touches a third-party server.

> **Live in production.** This is the actual system I use to manage my personal brokerage account. The autonomous routines run daily on a Railway server and commit research notes to git.

---

## Screenshots

### Opportunity Queue — AI-researched trade ideas, nothing executes without your approval
![Opportunity Queue](docs/opportunity-queue.png)

### One-tap Trade Approval — SMS and email with green Approve / red Deny buttons
![Email Approval](docs/email-approval.png)

### 3-Step Order Review — Enter → Review → Placed
![Order Review](docs/order-review.png)

### Holdings — Real-time positions, P&L, cost basis, day change
![Holdings](docs/holdings.png)

### Performance — Equity curve vs SPY, Sharpe ratio, max drawdown, win rate
![Performance](docs/performance.png)

### Risk Monitor — AI-flagged exit candidates with thesis analysis
![Risk Monitor](docs/risk-monitor.png)

### Morning Briefing — AI-generated daily briefing + news feed for your holdings
![Morning Briefing](docs/briefing.png)

---

## What it does

| Feature | Description |
|---|---|
| **Live Portfolio** | Real-time positions, P&L, cost basis, and sector allocation from Schwab |
| **AI Buy Scan** | Claude scans a curated watchlist, researches fundamentals + news, and proposes high-conviction buys — sent via SMS and email with one-tap Approve/Deny links |
| **AI Sell Scan** | Claude reviews open positions for exit candidates (loss thresholds, thesis breaks, concentration risk) — same approve/deny flow |
| **One-tap Trade Approval** | Tap Approve in SMS or email → confirmation page → Place Order → live Schwab order. No app needed. |
| **AI Portfolio Advisor** | Streaming chat powered by Claude with live tool-calling — fetches your portfolio, news, price history, and earnings before answering |
| **Risk Monitor** | Background scanner flags concentration risk, earnings proximity, drawdowns, and large gains every 30 minutes |
| **Performance Tracking** | Equity curve from your full transaction history with period filters (1M / 3M / 6M / 1Y / ALL) |
| **Earnings Calendar** | Upcoming earnings and key fundamentals for every position you hold |
| **AI News Feed** | Headlines for your holdings triaged by severity with analyst impact summaries |
| **Trade Journal** | Completed trades reconstructed from order history — win rate, expectancy, per-symbol stats |
| **Intermarket Analysis** | Yield curve, DXY, VIX, and sector rotation signals via FRED + market data |
| **SMS + Email Alerts** | Twilio SMS and SMTP email with HTML approve/deny buttons for every trade proposal |
| **Customizable Dashboard** | Adjustable alert thresholds, buy scan budget, email upside filter — all from the UI |

---

## How trade approval works

```
Buy/sell scan runs (scheduled or manual)
    └── Claude researches candidates with live tools
            get_portfolio · get_news · get_price_history
            get_stock_fundamentals · get_earnings_calendar
        └── Generates proposals with 24-hour approval tokens
            └── SMS: "BUY 5 NVDA @ $142.50 ~$712  ✅ approve  ❌ deny"
            └── Email: HTML card with green Approve / red Deny buttons
                └── Tap Approve → confirmation page → Place Order
                    └── Kill switch check → Risk policy check → Schwab preview → Live order
```

Nothing executes without your explicit tap. Tokens expire after 24 hours.

---

## Autonomous daily routines

The `routines/` directory contains five Claude Code cloud agent prompts that run on a market schedule. They deploy to Railway (always-on server) and commit research notes and snapshots to the `memory/` directory as persistent state across sessions.

```
Claude Code cloud routines (Railway, scheduled)
    └── scripts/schwab_server.sh <subcommand>   ← calls FastAPI server
            └── FastAPI server (Railway)          ← handles Schwab OAuth
                    └── Schwab API               ← real brokerage data

Memory persistence: routines commit memory/*.md to git after each run.
```

| Routine | Schedule | What it does |
|---|---|---|
| `pre-market.md` | 8:00 AM ET | Macro snapshot, held-position thesis checks, watchlist scan, account briefing |
| `market-open.md` | 9:45 AM ET | Validates buy signals, triggers buy scan if conditions are met |
| `midday.md` | 12:00 PM ET | Thesis check on news, exit threshold review, flags for user action |
| `daily-summary.md` | 4:15 PM ET | EOD P&L snapshot, position log, commits to `memory/TRADE-LOG.md` |
| `weekly-review.md` | Friday 4:00 PM ET | Full week review — alpha vs S&P, rule adherence, strategy updates |

All research and decisions are written to `memory/RESEARCH-LOG.md` and `memory/TRADE-LOG.md` — plain markdown files committed to git, so Claude has persistent context across every session without a database.

See [`routines/README.md`](routines/README.md) for Railway + Claude Code setup instructions.

---

## Tech stack

- **Backend:** Python 3.13, FastAPI, Uvicorn
- **AI:** Anthropic Claude (`claude-sonnet-4-6`) with multi-round tool-calling agent loop
- **Brokerage:** Charles Schwab Individual Trader API (OAuth 2.0, PKCE)
- **Market data:** yfinance, FRED API, SEC EDGAR
- **Notifications:** Twilio SMS + SMTP email
- **Frontend:** Vanilla JS, Chart.js — no framework, no build step
- **Deployment:** Railway (server), Claude Code scheduled agents (routines)

---

## Architecture

```
schwab_trader/
├── advisor/        # Claude streaming chat agent (tool-calling loop)
├── agent/          # Buy/sell scan + background risk monitor + alert store
│   ├── monitor.py  # Rule-based flag detection (drawdown, concentration, earnings)
│   ├── service.py  # Buy scan, sell scan, briefing generation
│   └── tools.py    # get_portfolio · get_news · get_price_history
│                   # get_earnings_calendar · get_stock_fundamentals
├── auth/           # Schwab OAuth 2.0 + token management
├── broker/         # Schwab API wrapper (accounts, orders, quotes, price history)
├── earnings/       # yfinance earnings calendar + fundamentals
├── edgar/          # SEC EDGAR filing data
├── execution/      # Kill switch → risk checks → order preview → place_order
├── fred/           # FRED macroeconomic indicators (yield curve, CPI, DXY)
├── intermarket/    # Cross-asset signal aggregation
├── journal/        # Trade reconstruction from order history + scorecard metrics
├── news/           # AI-triaged news feed
├── notifications/  # Twilio SMS + SMTP HTML email with approval tokens
├── performance/    # Equity curve from full transaction history
├── risk/           # Position risk models and policy engine
├── screening/      # Watchlist scoring (momentum + fundamentals)
├── thesis/         # AI thesis validation per position
└── server/         # FastAPI app + routes + single-file dashboard HTML
```

---

## Setup

### Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) package manager
- A [Schwab Developer App](https://developer.schwab.com) with Individual Trader API access
- An [Anthropic API key](https://console.anthropic.com)

### 1. Clone and install

```bash
git clone https://github.com/ongcpatrick/Schwab-API-Trader-Public.git
cd Schwab-API-Trader-Public
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required:
```env
SCHWAB_TRADER_SCHWAB_APP_KEY=your_schwab_app_key
SCHWAB_TRADER_SCHWAB_APP_SECRET=your_schwab_app_secret
SCHWAB_TRADER_SCHWAB_CALLBACK_URL=http://127.0.0.1:8000/auth/callback
SCHWAB_TRADER_ANTHROPIC_API_KEY=your_anthropic_api_key
```

Optional — enables SMS + email trade approvals:
```env
SCHWAB_TRADER_TWILIO_ACCOUNT_SID=
SCHWAB_TRADER_TWILIO_AUTH_TOKEN=
SCHWAB_TRADER_TWILIO_FROM_NUMBER=
SCHWAB_TRADER_ALERT_PHONE_NUMBER=
SCHWAB_TRADER_EMAIL_SMTP_HOST=smtp.gmail.com
SCHWAB_TRADER_EMAIL_SMTP_USER=you@gmail.com
SCHWAB_TRADER_EMAIL_SMTP_PASSWORD=your_app_password
SCHWAB_TRADER_ALERT_EMAIL_ADDRESS=you@gmail.com
SCHWAB_TRADER_DASHBOARD_URL=http://YOUR_LOCAL_IP:8000
```

Optional — enables macroeconomic indicators in the dashboard:
```env
SCHWAB_TRADER_FRED_API_KEY=   # Free key at https://fred.stlouisfed.org/docs/api/api_key.html
```

See `.env.example` for the full list including risk guardrails and alert thresholds.

### 3. Start

```bash
./start.sh
# or manually:
uv run uvicorn schwab_trader.server.app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://127.0.0.1:8000` to complete Schwab OAuth, then go to `http://127.0.0.1:8000/dashboard`.

---

## Safety

- **Kill switch** — `SCHWAB_TRADER_LIVE_ORDER_KILL_SWITCH=true` blocks all order execution instantly, no code changes needed
- **Risk policy** — every order goes through configurable daily loss limits, position size caps, and max open position checks before preview or placement
- **Human in the loop** — buy and sell proposals require explicit approval via SMS or email; nothing executes autonomously
- **Token expiry** — approval tokens expire after 24 hours
- **Audit log** — all order activity written to `.data/audit.jsonl`
- **Credentials stay local** — `.env`, token files, and trade data are all gitignored

---

## Disclaimer

This is a personal tool for educational and informational purposes. It places **real orders** on your brokerage account — always review proposals carefully before confirming. Past performance of any strategy shown does not guarantee future results. This is not financial advice.
