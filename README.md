# Schwab AI Trader

**An AI-powered trading copilot built on the Charles Schwab API and Claude — running live on my personal brokerage account.**

Every morning at 8 AM, an AI agent reads the market, checks my positions, scans my watchlist, and sends me a briefing. If it finds a trade worth making, it texts me. I tap Approve. The order goes in. I didn't write a single trading rule — I built the system that thinks through them.

This is not a backtest. This is not a paper trading demo. This runs on real money.

---

![Opportunity Queue](docs/opportunity-queue.png)

The dashboard surfaces AI-researched trade ideas ranked by conviction. Each card has a full fundamental thesis written by Claude — Piotroski scores, revenue growth, analyst upside, earnings windows, sector momentum. Nothing executes without your explicit approval.

---

## The problem it solves

Managing a stock portfolio requires attention at the wrong times — premarket, during earnings, when a position breaks down at 2 PM. Most people either over-trade trying to stay on top of it, or under-react because they're busy living their life.

This system watches so I don't have to. It reads news on my positions, checks exit thresholds, monitors concentration risk, and surfaces decisions — not noise. I stay in control of every order. The AI handles the research and the vigilance.

---

## How a trade gets proposed

The buy scan runs on a schedule. Claude pulls live portfolio data, checks the watchlist, reads fundamentals from EDGAR and yfinance, pulls recent news, and runs a multi-round analysis loop. If a position meets the buy criteria — analyst upside, earnings clearance, sector momentum — it generates a proposal and sends it to me.

That proposal lands in my inbox as an HTML email with a green **Approve** button and a red **Deny** button.

![Email Approval](docs/email-approval.png)

Tap Approve. A confirmation page loads. Review the details. Hit Place Order. Done. The whole flow works from your phone without ever opening the dashboard. Tokens expire after 24 hours — no stale approvals sitting around.

---

## The order flow

Approving a proposal opens a clean three-step flow: configure shares and order type, review the full order summary, and place it directly on your Schwab account.

![Enter Order](docs/order-review.png)

![Order Review](docs/review-screen.png)

Every order runs through a risk policy check before it ever reaches Schwab — kill switch, daily loss cap, position size limits, max open positions. The guardrails are enforced in code, not discipline.

---

## Your full portfolio, always current

The Holdings view pulls live data directly from Schwab — positions, day P&L, cost basis, unrealized gains, sector allocation. No manual entry. No syncing. It's your actual account.

![Holdings](docs/holdings.png)

---

## Risk monitoring that never sleeps

The risk monitor scans every 30 minutes while the market is open. It flags concentration risk, positions approaching earnings, drawdowns past exit thresholds, and large unrealized gains that might be worth locking in. When something needs attention, it sends an SMS.

When it finds a position that needs to be cut, it generates a sell proposal with the same approve/deny flow.

![Risk Monitor](docs/risk-monitor.png)

---

## Every morning starts with a briefing

At 8 AM ET, a Claude Code agent runs the pre-market routine. It reads macro conditions, checks news on every position I hold, looks at analyst upgrades and downgrades, and writes a briefing — committed directly to the repo as a markdown file. By the time the market opens, I know exactly what to watch.

![Morning Briefing](docs/briefing.png)

---

## Performance tracked from real history

The performance page reconstructs your equity curve from actual Schwab order history — no manual logging, no estimates. Toggle between 1M / 3M / 6M / 1Y / ALL, compare against SPY, and see Sharpe ratio, max drawdown, best/worst day, and win rate.

![Performance](docs/performance.png)

---

## Autonomous daily routines

Five Claude Code agents run on a market schedule, deployed on Railway. They call the FastAPI server, do their analysis, and commit their findings to a `memory/` directory in the repo as plain markdown files. Claude reads those files at the start of every session — persistent context without a database.

| Routine | Schedule | What it does |
|---|---|---|
| `pre-market.md` | 8:00 AM ET | Macro snapshot, thesis checks, watchlist scan, daily briefing |
| `market-open.md` | 9:45 AM ET | Validates buy signals, triggers buy scan if conditions are met |
| `midday.md` | 12:00 PM ET | News check on positions, exit threshold review, flags for user action |
| `daily-summary.md` | 4:15 PM ET | EOD P&L snapshot committed to `memory/TRADE-LOG.md` |
| `weekly-review.md` | Friday 4:00 PM ET | Full week review — alpha vs S&P, rule adherence, strategy updates |

```
Claude Code cloud routines (Railway, scheduled)
    └── scripts/schwab_server.sh        ← bash wrapper for all server calls
            └── FastAPI server           ← handles Schwab OAuth + data
                    └── Schwab API       ← real brokerage

Memory: routines commit memory/*.md to git → Claude reads them next session
```

See [`routines/README.md`](routines/README.md) for the full Railway + Claude Code setup.

---

## Tech stack

- **Backend:** Python 3.13, FastAPI, Uvicorn
- **AI:** Anthropic Claude (`claude-sonnet-4-6`) — multi-round tool-calling agent loop
- **Brokerage:** Charles Schwab Individual Trader API (OAuth 2.0, PKCE)
- **Market data:** yfinance, FRED API, SEC EDGAR
- **Notifications:** Twilio SMS + SMTP email with HTML approve/deny buttons
- **Frontend:** Vanilla JS, Chart.js — no framework, no build step
- **Deployment:** Railway (always-on server), Claude Code (scheduled routines)

---

## Architecture

```
schwab_trader/
├── advisor/        # Claude streaming chat with live tool-calling
├── agent/          # Buy/sell scan, risk monitor, alert store
│   ├── monitor.py  # Rule-based flag detection
│   ├── service.py  # Scan orchestration
│   └── tools.py    # get_portfolio · get_news · get_price_history
│                   # get_earnings_calendar · get_stock_fundamentals
├── auth/           # Schwab OAuth 2.0 + PKCE token management
├── broker/         # Schwab API wrapper
├── execution/      # Kill switch → risk checks → preview → place_order
├── fred/           # FRED macroeconomic data
├── intermarket/    # Cross-asset signal aggregation
├── journal/        # Trade reconstruction + scorecard metrics
├── notifications/  # Twilio SMS + SMTP email with approval tokens
├── performance/    # Equity curve from full order history
├── risk/           # Position risk models and policy engine
├── screening/      # Watchlist scoring
├── thesis/         # AI thesis validation per position
└── server/         # FastAPI app + single-file dashboard HTML
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
# Edit .env — four required keys, everything else is optional
```

**Required:**
```env
SCHWAB_TRADER_SCHWAB_APP_KEY=your_schwab_app_key
SCHWAB_TRADER_SCHWAB_APP_SECRET=your_schwab_app_secret
SCHWAB_TRADER_SCHWAB_CALLBACK_URL=http://127.0.0.1:8000/auth/callback
SCHWAB_TRADER_ANTHROPIC_API_KEY=your_anthropic_api_key
```

**Optional — SMS + email trade approvals:**
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

**Optional — macroeconomic indicators:**
```env
SCHWAB_TRADER_FRED_API_KEY=   # Free at https://fred.stlouisfed.org/docs/api/api_key.html
```

See `.env.example` for the full list including risk guardrails and alert thresholds.

### 3. Start

```bash
./start.sh
```

Open `http://127.0.0.1:8000` to complete Schwab OAuth. You'll be redirected to the dashboard automatically.

---

## Safety

This system places real orders. The guardrails are not optional:

- **Kill switch** — flip `SCHWAB_TRADER_LIVE_ORDER_KILL_SWITCH=true` to block all order execution instantly without changing any code
- **Risk policy** — every order checks daily loss limits, position size caps, and max open positions before it reaches Schwab
- **Human in the loop** — no order executes without your explicit tap on an approve link; the AI proposes, you decide
- **Token expiry** — approval tokens are single-use and expire after 24 hours
- **Audit log** — every order attempt (approved, denied, or blocked) is written to `.data/audit.jsonl`
- **Credentials stay local** — `.env`, tokens, and trade data are all gitignored and never leave your machine

---

## Disclaimer

This is a personal project for educational and informational purposes. It places **real orders** on your brokerage account. Always review proposals carefully before approving. Past performance does not guarantee future results. This is not financial advice.
