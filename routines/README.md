# Routines

Five Claude Code cloud routines that run on a weekday schedule.
They complement the FastAPI server (which handles real-time execution)
by adding research documentation, memory persistence, and weekly review.

## Architecture

```
FastAPI server (24/7 local)          Claude Code routines (scheduled)
├── Real-time monitoring         ←→  ├── Pre-market research + briefing
├── Schwab OAuth + execution          ├── Market-open buy validation
├── Buy scan agent (automated)        ├── Midday thesis check
├── Dashboard UI                      ├── EOD snapshot + P&L tracking
└── SMS/email notifications           └── Friday weekly review
                                           ↓
                                      memory/*.md  →  git commit  →  main
```

## Cron Schedule (US Eastern)

| Routine         | File                    | Cron (ET)      |
|-----------------|-------------------------|----------------|
| Pre-market      | `pre-market.md`         | `0 8 * * 1-5`  |
| Market-open     | `market-open.md`        | `30 9 * * 1-5` |
| Midday          | `midday.md`             | `0 12 * * 1-5` |
| Daily summary   | `daily-summary.md`      | `0 16 * * 1-5` |
| Weekly review   | `weekly-review.md`      | `0 17 * * 5`   |

## Setup

### 1. Required environment variable on each routine
```
SERVER_URL=http://YOUR_SERVER_IP:8000
```
This must be the publicly accessible URL of your FastAPI server.
Options: Tailscale funnel, ngrok, or your home IP with port 8000 forwarded.

### 2. GitHub repo access
Install the Claude GitHub App on this repo so cloud routines can clone and push.
In each routine's environment settings, enable **"Allow unrestricted branch pushes"**.

### 3. Create routines in Claude Code cloud
For each routine:
1. Go to Routines → New Routine
2. Select this GitHub repo, branch: `main`
3. Set the cron schedule and timezone
4. Set `SERVER_URL` environment variable
5. Paste the prompt from the relevant `.md` file verbatim
6. Enable "Allow unrestricted branch pushes"
7. Click "Run now" to test before waiting for the cron

### 4. Seed the TRADE-LOG baseline
After server is running, take a manual snapshot to give routines a Day 0 baseline:
```bash
bash scripts/schwab_server.sh accounts
```
Copy the portfolio value into `memory/TRADE-LOG.md` under the Day 0 entry.

## Local Testing
Run any routine prompt manually in Claude Code by pasting the routine's content.
Set `SERVER_URL` to `http://localhost:8000` in your shell before running.

```bash
export SERVER_URL=http://localhost:8000
bash scripts/schwab_server.sh ping   # verify server is up
```

## Notes
- Routines are research + memory only. Trade execution requires your explicit approval via SMS/email.
- The server's built-in scheduler handles buy scanning and exit monitoring between routine runs.
- If a routine run fails (server unreachable, etc.), the next run recovers by reading git state.
- Memory files are append-only dated sections — merge conflicts are nearly impossible.
