# Schwab AI Trader

A self-hosted, AI-powered portfolio management dashboard built on the **Charles Schwab brokerage API** and **Claude**. Runs entirely on your own machine — your data never touches a third-party server.

---

## What it does

| Feature | Description |
|---|---|
| **Live Portfolio** | Real-time positions, P&L, cost basis, and sector allocation from Schwab |
| **AI Buy Scan** | Claude scans a curated watchlist, researches fundamentals + news, and proposes high-conviction buys — sent to you via SMS and email with one-tap Approve/Deny links |
| **AI Sell Scan** | Claude reviews your open positions for exit candidates (loss thresholds, thesis breaks, concentration risk) — same approve/deny flow |
| **One-tap Trade Approval** | Tap Approve in SMS or email → confirmation page → Place Order → live Schwab order. No app needed. |
| **AI Portfolio Advisor** | Streaming chat powered by Claude with live tool-calling — fetches your portfolio, news, price history, and earnings before answering |
| **Risk Monitor** | Background scanner flags concentration risk, earnings proximity, drawdowns, and large gains every 30 minutes |
| **Performance Tracking** | Equity curve from your full transaction history with period filters (1M / 3M / 6M / 1Y / ALL) |
| **Earnings Calendar** | Upcoming earnings and key fundamentals for every position you hold |
| **AI News Feed** | Headlines for your holdings triaged by severity with analyst impact summaries |
| **Trade Journal** | Completed trades reconstructed from order history — win rate, expectancy, per-symbol stats |
| **SMS + Email Alerts** | Twilio SMS and SMTP email with HTML approve/deny buttons for every trade proposal |
| **Customizable Dashboard** | Adjustable alert thresholds, buy scan budget, email upside filter — all from the UI |

---

## How trade approval works

```
Buy/sell scan runs (scheduled or manual)
    └── Claude researches candidates with live tools
        └── Generates proposals with 24-hour approval tokens
            └── SMS: "BUY 5 NVDA @ $142.50 ~$712  ✅ approve  ❌ deny"
            └── Email: HTML card with green Approve / red Deny buttons
                └── Tap Approve → confirmation page → Place Order
                    └── Live order placed on your Schwab account
```

Nothing executes without your explicit tap. Tokens expire after 24 hours.

---

## Tech stack

- **Backend:** Python 3.13, FastAPI, Uvicorn
- **AI:** Anthropic Claude (`claude-sonnet-4-6`) with multi-round tool-calling agent loop
- **Brokerage:** Charles Schwab Individual Trader API (OAuth 2.0, PKCE)
- **Market data:** yfinance (earnings, fundamentals, price history)
- **Notifications:** Twilio SMS + SMTP email
- **Frontend:** Vanilla JS, Chart.js — no framework, no build step

---

## Architecture

```
schwab_trader/
├── advisor/        # Claude streaming chat agent (tool-calling loop)
├── agent/          # Buy/sell scan + background risk monitor + alert store
│   ├── monitor.py  # Rule-based flag detection
│   ├── service.py  # Buy scan, sell scan, briefing generation
│   └── tools.py    # get_portfolio, get_news, get_price_history, get_earnings_calendar, get_stock_fundamentals
├── auth/           # Schwab OAuth 2.0 + token management
├── broker/         # Schwab API wrapper (accounts, orders, quotes, price history)
├── earnings/       # yfinance earnings calendar + fundamentals
├── execution/      # Risk checks → order preview → place_order (guarded execution)
├── journal/        # Trade reconstruction from order history + scorecard metrics
├── news/           # AI-triaged news feed
├── notifications/  # Twilio SMS + SMTP HTML email
├── performance/    # Equity curve from transaction history
├── risk/           # Position risk models and policy engine
├── screening/      # Watchlist scoring (momentum + fundamentals)
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
git clone https://github.com/YOUR_USERNAME/schwab-ai-trader.git
cd schwab-ai-trader
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required variables:
```env
SCHWAB_TRADER_SCHWAB_APP_KEY=your_schwab_app_key
SCHWAB_TRADER_SCHWAB_APP_SECRET=your_schwab_app_secret
SCHWAB_TRADER_SCHWAB_CALLBACK_URL=http://127.0.0.1:8000/auth/callback
SCHWAB_TRADER_ANTHROPIC_API_KEY=your_anthropic_api_key
```

Optional (enables SMS + email trade approvals):
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

### 3. Start

```bash
./start.sh
# or manually:
uv run uvicorn schwab_trader.server.app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://127.0.0.1:8000` to complete Schwab OAuth, then go to `http://127.0.0.1:8000/dashboard`.

---

## Optional: Claude Code routines

The `routines/` directory contains five Claude Code scheduled task prompts that run on a daily market schedule (pre-market research, market-open validation, midday thesis check, EOD snapshot, Friday weekly review). They commit research notes and P&L snapshots to a `memory/` directory in your repo as persistent state.

See [`routines/README.md`](routines/README.md) for setup instructions.

---

## Safety

- The kill switch (`SCHWAB_TRADER_LIVE_ORDER_KILL_SWITCH=true`) blocks all order execution instantly
- Every order goes through a risk policy check before preview or placement
- Approval tokens expire after 24 hours
- All order activity is written to an audit log (`.data/audit.jsonl`)
- Your `.env` is gitignored — credentials never leave your machine

---

## Disclaimer

This is a personal tool for educational and informational purposes. It places **real orders** on your brokerage account — always review proposals carefully before confirming. This is not financial advice.
