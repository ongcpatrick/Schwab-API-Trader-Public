# Project AGENTS.md

## Project Summary

- Name: `Schwab API Trader`
- Type: `tool`
- Goal: Build a local-first Schwab trading copilot that can evaluate trades, automate safe workflows, and optionally submit guardrailed orders through the official API.
- Primary users: The owner of the linked Schwab brokerage account(s)

## Tech Stack

- Framework: `FastAPI` for a local control plane plus scheduled/background workers
- Language: `Python`
- Package manager: `uv`
- Deploy target: `local-first` with optional `Docker`

## Commands

- Install: `uv sync`
- Dev: `uv run uvicorn src.server.app:app --reload`
- Lint: `uv run ruff check .`
- Test: `uv run pytest`
- Build: `docker build -t schwab-api-trader .`

## Working Rules

- Plan before implementing non-trivial features or refactors.
- Default to read-only or `previewOrder` flows before any live order placement.
- Never hardcode Schwab app keys, secrets, refresh tokens, access tokens, or account identifiers.
- Prefer the official Schwab API over browser automation whenever the API covers the workflow.
- Keep files small and modular, organized by domain: auth, data, strategy, risk, execution, journaling.
- Add or update tests when behavior changes, especially for risk rules and order construction.
- Every execution path must produce an audit trail with inputs, policy checks, broker responses, and timestamps.
- Use encrypted account hashes where Schwab requires them; do not treat raw account numbers as routable API identifiers.
- Review for correctness, regressions, security, and unintended trading behavior before finishing.

## Product Constraints

- Must-have behavior:
- read account, position, order, transaction, and market data from Schwab
- auto-journal trades and compute evaluation metrics
- preview orders before submission
- enforce risk policies before any live order placement
- provide a kill switch and clear operator override path
- Non-goals:
- high-frequency trading
- opaque autonomous trading with no human-defined policy
- credential sharing with third-party auto-trading services
- website scraping or browser automation for order entry when the official API is available
- Performance expectations:
- local risk checks should complete quickly enough to gate orders synchronously
- polling and scheduled jobs must respect Schwab rate limits
- system should degrade safely by refusing to trade when data, auth, or policy state is stale
- Security constraints:
- secrets only via environment variables or an approved local secrets store
- token persistence must be protected and never committed
- all external inputs validated at system boundaries
- all live trading actions must be logged and attributable

## Design Notes

- Visual direction: `technical`
- Brand tone: `direct`
- UI constraints: `desktop-first`, audit-first, readable tables and timelines, no flashy trading-guru styling

## Architecture Notes

- Important directories:
- `src/auth` for OAuth and token lifecycle
- `src/schwab` for API clients and schemas
- `src/market_data` for quotes, chains, history, and market hours
- `src/journal` for fills, trades, metrics, and reports
- `src/strategy` for signal generation and evaluation
- `src/risk` for position sizing, limits, and policy checks
- `src/execution` for preview, placement, cancel, replace, and kill-switch logic
- `src/server` for API/UI entry points
- `tests` for unit, integration, and safety tests
- Data sources: `Schwab Trader API`, `Schwab Market Data API`, local database for journals, policies, and audit logs
- Integration points: OAuth, order preview/placement, market hours, quotes, option chains, local scheduling, optional notifications

## Definition Of Done

- The feature works end-to-end in the intended mode: read-only, preview, or live.
- Tests or verification steps cover the change, including failure paths where relevant.
- Risk policies are enforced for any touched execution flow.
- No obvious regressions, dead code, or unsafe defaults were introduced.
- Documentation is updated if workflow, safety assumptions, or operating procedures changed.

## Project References

- Product brief: `./PROJECT.md`

## Notes For Codex

- Treat this file as the project-specific operating overlay for this workspace.
- If requirements shift, update `PROJECT.md` before major implementation work.
- When in doubt, optimize for capital preservation, explainability, and auditability over automation depth.
