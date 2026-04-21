"""Trading agent — monitors portfolio and raises actionable flags."""

from __future__ import annotations

import json
import logging
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from schwab_trader.advisor.service import AdvisorService
from schwab_trader.agent.monitor import check_portfolio
from schwab_trader.agent.store import AlertStore
from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.earnings.service import get_earnings_calendar
from schwab_trader.intermarket.service import Regime, detect_regime
from schwab_trader.screening.service import screen_candidates

logger = logging.getLogger(__name__)

# System prompt for the portfolio scan agent — separate from the chat advisor prompt.
_SCAN_SYSTEM = (
    "You are a portfolio risk manager for a personal retail investor. "
    "You have live tools: get_portfolio, get_news, get_earnings_calendar, get_price_history. "
    "Use them to enrich your analysis before producing output. "
    "No Markdown of any kind. No em-dashes, no asterisks, no # headers, no bullet dashes. "
    "Plain readable English only."
)

_PROPOSALS_PROMPT = """Based on the following portfolio flags, use your tools to look up
current news and earnings for flagged symbols, then generate specific trade proposals as JSON.
Only propose trades with strong justification. Be conservative — when in doubt, don't propose.

FLAGS:
{flags_text}

CURRENT POSITIONS:
{positions_text}

Use get_news and get_earnings_calendar for the flagged symbols before deciding.
Then return ONLY valid JSON (no markdown, no explanation):
{{
  "proposals": [
    {{
      "symbol": "TSM",
      "action": "SELL",
      "quantity": 1,
      "order_type": "LIMIT",
      "limit_price": 384.12,
      "reasoning": "Trim before earnings in 2 days to lock 37.5% gain. Keep remaining shares for upside.",
      "urgency": "HIGH"
    }}
  ]
}}

Rules:
- action: "BUY" or "SELL" only
- order_type: "MARKET" or "LIMIT"
- limit_price: null for MARKET orders, a specific price for LIMIT
- quantity must be a positive number, never exceed current holdings for SELL
- urgency: "HIGH" (act today), "MEDIUM" (this week), "LOW" (consider)
- If no trades are warranted, return {{"proposals": []}}"""

_ANALYSIS_PROMPT = """You are a portfolio risk manager reviewing flags for a personal retail investor.

PORTFOLIO VALUE: ${portfolio_value:,.2f}

FLAGS:
{flags_text}

POSITIONS:
{positions_text}

Use get_news and get_earnings_calendar for the flagged symbols to enrich your analysis.
Then return ONLY valid JSON, no markdown, no prose outside the JSON:
{{
  "verdict": "one plain sentence bottom line (no special characters, no markdown)",
  "items": [
    {{
      "symbol": "TICKER",
      "urgency": "NOW" | "WATCH" | "FYI",
      "title": "short plain phrase, max 8 words",
      "detail": "1-2 plain sentences. Specific numbers only. No asterisks, no dashes, no markdown."
    }}
  ]
}}

Rules:
- urgency NOW = act today, WATCH = monitor this week, FYI = informational only
- No Markdown formatting of any kind (no **, no #, no >, no --, no | tables)
- No em-dashes, no fancy punctuation, just plain readable English
- detail must be under 25 words
- Group duplicate symbols into one item
- Most urgent items first"""


_BUY_SCAN_SYSTEM = (
    "You are a buy-side analyst with access to professional-grade research tools. "
    "Always start by calling get_macro_context to assess the market environment — "
    "if the regime is BEARISH, raise the conviction bar significantly and propose fewer or no trades. "
    "Then call get_portfolio to understand the investor's current holdings and style. "
    "Available tools: get_macro_context, get_portfolio, get_stock_fundamentals, get_technical_indicators, "
    "get_insider_activity, get_earnings_revisions, get_news, get_earnings_calendar, get_price_history. "
    "Use them thoroughly before recommending. No Markdown. Plain readable English only."
)

_BUY_PROPOSALS_PROMPT = """You are evaluating buy candidates for an investor. Budget per trade: ${budget:.2f}

Start by calling get_portfolio to understand the investor's style from their current holdings.

PRE-SCREENED CANDIDATES (scored by momentum + fundamentals, best first):
{candidates_text}

ALREADY HELD (do not propose these): {held_symbols_text}
ALREADY PENDING BUY PROPOSALS (do not duplicate): {pending_symbols_text}

Research workflow — run ALL steps before proposing:
0. get_macro_context → check market regime (BULLISH/NEUTRAL/BEARISH), VIX level, sector ETF momentum
   - If BEARISH: raise conviction bar — only propose if all signals are exceptional
   - Check sector momentum: prefer candidates in leading sectors
1. get_portfolio → understand the investor's existing positions and sector style
2. get_stock_fundamentals on top 6-8 candidates → Piotroski F-score, forward PE, revenue growth, analyst upside, short interest %
3. get_technical_indicators on your shortlist → RSI-14 and 200-day MA (only buy if above 200MA or strong catalyst)
4. get_insider_activity on your shortlist → any CEO/CFO buying or congressional purchases in last 90 days
5. get_earnings_revisions on your shortlist → are analysts raising or cutting estimates?
6. get_news on your shortlist → check for near-term risks or catalysts
7. get_earnings_calendar → skip any stock with earnings within 3 days

Scoring guide (all must pass for HIGH conviction):
- Macro environment not BEARISH (or exceptionally strong thesis if it is)
- Fundamentals strong (Piotroski >= 6, revenue growth > 10%, analyst upside > 15%)
- Technical entry valid (above 200MA, RSI not overbought > 75)
- Short interest < 20% (avoid heavily shorted names unless momentum is very strong)
- Estimate revisions neutral or rising (not cutting)
- No earnings within 3 days
- Bonus: insider buying or congressional purchase is a strong positive signal
- Bonus: candidate sector is outperforming vs macro sector ETFs

Propose up to {max_proposals} BUY orders. Only propose if conviction is HIGH.
For each: quantity = floor(budget / current_price). Skip if less than 1 share.
Prefer LIMIT at last price. Use MARKET only for ETFs.

Return ONLY valid JSON, no markdown, no explanation outside the JSON:
{{
  "proposals": [
    {{
      "symbol": "NVDA",
      "action": "BUY",
      "quantity": 5,
      "order_type": "LIMIT",
      "limit_price": 142.50,
      "reasoning": "Piotroski 8/9, 42% revenue growth, analyst target $185 (+30%). Above 200MA, RSI 48 (neutral). CEO bought $2M last month. Analysts raised Q2 EPS estimates 3x in 30 days. No earnings for 6 weeks.",
      "urgency": "MEDIUM"
    }}
  ]
}}

If no candidates meet a high-conviction bar, return {{"proposals": []}}"""


_BRIEFING_SYSTEM = (
    "You are a sharp personal portfolio advisor giving a morning briefing. "
    "Use your tools proactively to fetch live data — always call get_portfolio first, "
    "then get_earnings_calendar for held symbols, then get_news for key holdings. "
    "Be direct and specific. Use real numbers. No Markdown, no asterisks, no em-dashes."
)

_BRIEFING_PROMPT = """Give me a concise morning portfolio briefing.
1. Call get_portfolio to see current positions and values.
2. Call get_earnings_calendar for all held symbols.
3. Call get_news for the top 3 holdings by value.

Return ONLY valid JSON, no markdown, no explanation:
{
  "headline": "One sentence bottom line with a specific number — e.g. 'Portfolio up 4.1% this month led by NVDA; TSM earnings tomorrow is the key risk'",
  "bullets": [
    "Specific insight 1 — max 20 words with a real number",
    "Specific insight 2",
    "Specific insight 3"
  ],
  "top_watch": "SYMBOL — one specific reason this is most important to watch today",
  "action": "One specific action to consider, or 'No action needed — maintain current positions'"
}
Exactly 3 bullets. Sharp and concise."""

_BRIEFING_EXIT_SYSTEM = (
    "You are a portfolio risk manager checking exit conditions. "
    "Be direct. No Markdown."
)

_SELL_SCAN_SYSTEM = (
    "You are a sell-side portfolio analyst. "
    "Identify positions that should be trimmed or exited based on: loss thresholds, thesis breaks, "
    "concentration risk, valuation stretch, or earnings danger. Be conservative — only recommend "
    "selling when conviction is HIGH. Use your tools to verify before recommending. "
    "No Markdown. Plain readable English only."
)

_SELL_PROPOSALS_PROMPT = """Review this portfolio for exit candidates.

POSITIONS:
{positions_text}

EXIT RULES (investor strategy):
- Unrealized loss <= -20%: Strong exit signal — cut loss
- Unrealized loss <= -15% with unclear thesis: Trim candidate
- Position > 25% of portfolio: Concentration risk — consider trimming
- Analyst consensus SELL or UNDERPERFORM: Flag for exit
- Unrealized gain >= +50%: Consider locking partial profits if thesis weakening

Instructions:
1. Call get_portfolio to confirm live current prices and P&L.
2. Use get_news for any position showing large losses, gains, or sector stress.
3. Use get_earnings_calendar to flag near-term earnings risk.
4. Use get_stock_fundamentals for positions with large gains (check if valuation stretched).
5. Propose SELL orders for up to {{max_proposals}} positions. Only HIGH conviction exits.
6. For partial exits (trim), set quantity < held shares. For full exits, use full held quantity.
7. Use LIMIT orders at or slightly below current market price.

Return ONLY valid JSON, no markdown:
{{
  "proposals": [
    {{
      "symbol": "AMD",
      "action": "SELL",
      "quantity": 6,
      "order_type": "LIMIT",
      "limit_price": 85.50,
      "reasoning": "Down 28% from entry at $119. NVDA dominating AI GPU market. Cutting per -20% loss rule.",
      "urgency": "HIGH"
    }}
  ]
}}

If no exits are warranted, return {{"proposals": []}}"""


def _normalize(p: dict) -> dict:
    qty = (p.get("longQuantity") or 0) - (p.get("shortQuantity") or 0)
    avg = p.get("averagePrice") or 0
    mkt = p.get("marketValue") or 0
    day_pct = p.get("currentDayProfitLossPercentage") or 0
    day_pnl = p.get("currentDayProfitLoss") or 0
    cost = abs(qty) * avg
    return {
        "symbol": p["instrument"]["symbol"],
        "qty": qty,
        "avg_cost": avg,
        "market_value": mkt,
        "cost_basis": cost,
        "day_pnl": day_pnl,
        "day_pct": day_pct,
    }


class AgentService:
    def __init__(self, store: AlertStore) -> None:
        self._store = store

    def run_check(
        self,
        broker_service: SchwabBrokerService,
        advisor_service: AdvisorService,
        *,
        settings,
    ) -> dict | None:
        """Run a full portfolio scan. Returns new alert dict if flags found, else None."""
        try:
            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                return None

            acct = accounts[0].get("securitiesAccount", {})
            raw = acct.get("positions", [])
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            portfolio_value = float(bal.get("liquidationValue") or 0)

            positions = [_normalize(p) for p in raw if p.get("instrument")]
            symbols = [p["symbol"] for p in positions]
            calendar = get_earnings_calendar(symbols)

            muted = set(self._store.get_muted_symbols().keys())
            flags = check_portfolio(
                positions,
                calendar,
                portfolio_value,
                earnings_days_threshold=settings.alert_earnings_days,
                position_down_pct=settings.alert_position_down_pct,
                day_loss_pct=settings.alert_day_loss_pct,
                concentration_pct=settings.alert_concentration_pct,
                gain_alert_pct=settings.alert_gain_pct,
                muted_symbols=muted,
            )

            if not flags:
                logger.info("Agent check: no flags detected")
                return None

            # Deduplicate — skip flags already in pending alerts
            recent_keys = self._store.get_recent_flag_keys()
            new_flags = [f for f in flags if (f.type, f.symbol) not in recent_keys]
            if not new_flags:
                logger.info("Agent check: all flags already alerted, skipping")
                return None

            flags_text = "\n".join(
                f"  [{f.severity}] {f.type}: {f.description}" for f in new_flags
            )
            positions_text = "\n".join(
                f"  {p['symbol']}: {p['qty']:.4f}sh @ avg ${p['avg_cost']:.2f}, "
                f"mkt ${p['market_value']:,.2f}, day {p['day_pct']:+.1f}%"
                for p in positions
            )

            # Build Claude analysis via agent loop (can call get_news / get_earnings_calendar)
            analysis_prompt = _ANALYSIS_PROMPT.format(
                portfolio_value=portfolio_value,
                flags_text=flags_text,
                positions_text=positions_text,
            )
            raw_analysis = advisor_service.run_agent(analysis_prompt, system_override=_SCAN_SYSTEM)
            try:
                analysis: str | dict = json.loads(raw_analysis)
            except Exception:
                analysis = raw_analysis

            # Generate structured trade proposals via agent loop
            proposals: list[dict] = []
            try:
                proposals_prompt = _PROPOSALS_PROMPT.format(
                    flags_text=flags_text,
                    positions_text=positions_text,
                )
                raw_json = advisor_service.run_agent(
                    proposals_prompt, system_override=_SCAN_SYSTEM
                )
                parsed = json.loads(raw_json)
                for p in parsed.get("proposals", []):
                    proposals.append({
                        "id": str(uuid.uuid4()),
                        "symbol": p["symbol"],
                        "action": p["action"],
                        "quantity": float(p["quantity"]),
                        "order_type": p.get("order_type", "MARKET"),
                        "limit_price": p.get("limit_price"),
                        "reasoning": p.get("reasoning", ""),
                        "urgency": p.get("urgency", "MEDIUM"),
                        "status": "pending",
                    })
            except Exception:
                logger.debug("Proposal generation skipped or failed (non-fatal)")

            alert = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "flags": [f.to_dict() for f in new_flags],
                "claude_analysis": analysis,
                "proposals": proposals,
                "portfolio_value": portfolio_value,
                "status": "pending",
                "sms_sent": False,
            }
            self._store.save_alert(alert)
            logger.info("Agent: %d new flag(s) saved (alert %s)", len(new_flags), alert["id"])
            return alert

        except Exception:
            logger.exception("Agent check failed")
            return None

    def run_buy_scan(
        self,
        broker_service: SchwabBrokerService,
        advisor_service: AdvisorService,
        *,
        settings,
    ) -> dict | None:
        """Run a buy-side watchlist scan. Returns new alert dict if proposals found."""
        try:
            # Gate on market regime — suppress buys in bear/risk-off conditions
            if getattr(settings, "regime_enabled", True):
                regime = detect_regime()
                logger.info("Buy scan: detected market regime = %s", regime.value)
                if regime in (Regime.BEAR, Regime.RISK_OFF):
                    logger.warning(
                        "Buy scan suppressed: market regime is %s — no new longs recommended",
                        regime.value,
                    )
                    return None

            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                return None

            acct = accounts[0].get("securitiesAccount", {})
            raw = acct.get("positions", [])
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            portfolio_value = float(bal.get("liquidationValue") or 0)

            held_symbols: set[str] = {
                p["instrument"]["symbol"]
                for p in raw
                if p.get("instrument")
            }
            pending_symbols = self._store.get_pending_buy_symbols()
            excluded = held_symbols | pending_symbols

            watchlist = [
                s.strip().upper()
                for s in settings.buy_scan_watchlist.split(",")
                if s.strip()
            ]
            candidates = screen_candidates(
                broker_service,
                excluded_symbols=excluded,
                top_n=15,
                watchlist=watchlist or None,
            )
            if not candidates:
                logger.info("Buy scan: no candidates after exclusions")
                return None

            candidates_text = "\n".join(f"  {c.summary}" for c in candidates)
            held_symbols_text = ", ".join(sorted(held_symbols)) or "none"
            pending_symbols_text = ", ".join(sorted(pending_symbols)) or "none"

            prompt = _BUY_PROPOSALS_PROMPT.format(
                budget=settings.buy_scan_budget,
                candidates_text=candidates_text,
                held_symbols_text=held_symbols_text,
                pending_symbols_text=pending_symbols_text,
                max_proposals=settings.buy_scan_max_proposals,
            )

            raw_json = advisor_service.run_agent(
                prompt, system_override=_BUY_SCAN_SYSTEM, max_rounds=12
            )
            logger.info("Buy scan raw response (%d chars): %r", len(raw_json or ""), (raw_json or "")[:300])
            if not raw_json or not raw_json.strip():
                logger.warning("Buy scan: Claude returned empty response")
                return None
            # Strip markdown code fences if Claude wrapped the JSON
            stripped = raw_json.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("```", 2)[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                stripped = stripped.rsplit("```", 1)[0].strip()
            if not stripped:
                logger.warning("Buy scan: response was only code fences — raw: %r", raw_json[:200])
                return None
            # Find the JSON object boundary in case there's surrounding prose
            start = stripped.find("{")
            end   = stripped.rfind("}") + 1
            if start == -1 or end == 0:
                logger.warning("Buy scan: no JSON object found in response — raw: %r", stripped[:200])
                return None
            parsed = json.loads(stripped[start:end])

            proposals: list[dict] = []
            expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

            for p in parsed.get("proposals", []):
                price = float(p.get("limit_price") or 0)
                quantity = math.floor(settings.buy_scan_budget / price) if price > 0 else 0
                if quantity < 1:
                    logger.debug("Buy scan: skipping %s — quantity < 1 at $%.2f", p.get("symbol"), price)
                    continue
                proposals.append({
                    "id": str(uuid.uuid4()),
                    "symbol": p["symbol"],
                    "action": "BUY",
                    "quantity": float(quantity),
                    "order_type": p.get("order_type", "LIMIT"),
                    "limit_price": p.get("limit_price"),
                    "reasoning": p.get("reasoning", ""),
                    "urgency": p.get("urgency", "MEDIUM"),
                    "status": "pending",
                    "approval_token": secrets.token_hex(32),
                    "denial_token": secrets.token_hex(32),
                    "token_expires_at": expires_at,
                })

            if not proposals:
                logger.info("Buy scan: Claude found no high-conviction candidates")
                return None

            alert = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "alert_type": "BUY_SCAN",
                "flags": [],
                "claude_analysis": None,
                "proposals": proposals,
                "portfolio_value": portfolio_value,
                "budget": settings.buy_scan_budget,
                "status": "pending",
                "sms_sent": False,
                "email_sent": False,
            }
            self._store.save_alert(alert)
            logger.info("Buy scan: %d proposal(s) saved (alert %s)", len(proposals), alert["id"])
            return alert

        except Exception:
            logger.exception("Buy scan failed")
            return None

    def generate_briefing(
        self,
        broker_service: SchwabBrokerService,
        advisor_service: AdvisorService,
    ) -> dict | None:
        """Generate a daily AI portfolio briefing."""
        try:
            raw = advisor_service.run_agent(
                _BRIEFING_PROMPT, system_override=_BRIEFING_SYSTEM, max_rounds=8
            )
            if not raw or not raw.strip():
                return None
            stripped = raw.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("```", 2)[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                stripped = stripped.rsplit("```", 1)[0].strip()
            start = stripped.find("{")
            end = stripped.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            parsed = json.loads(stripped[start:end])
            parsed["generated_at"] = datetime.now().isoformat()
            return parsed
        except Exception:
            logger.exception("Briefing generation failed")
            return None

    def run_sell_scan(
        self,
        broker_service: SchwabBrokerService,
        advisor_service: AdvisorService,
        *,
        settings,
    ) -> dict | None:
        """Scan open positions for exit candidates. Returns alert dict if proposals found."""
        try:
            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                return None

            acct = accounts[0].get("securitiesAccount", {})
            raw = acct.get("positions", [])
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            portfolio_value = float(bal.get("liquidationValue") or 0)

            positions = [_normalize(p) for p in raw if p.get("instrument")]
            if not positions:
                return None

            positions_text = "\n".join(
                f"  {p['symbol']}: {p['qty']:.0f}sh @ avg ${p['avg_cost']:.2f}, "
                f"mkt ${p['market_value']:,.2f}, "
                f"P&L {((p['market_value'] - p['cost_basis']) / p['cost_basis'] * 100) if p['cost_basis'] else 0:+.1f}%, "
                f"weight {p['market_value'] / portfolio_value * 100:.1f}% of portfolio"
                for p in positions
                if p.get("cost_basis") and p["cost_basis"] > 0
            )

            max_proposals = getattr(settings, "buy_scan_max_proposals", 3)
            prompt = _SELL_PROPOSALS_PROMPT.format(
                positions_text=positions_text,
                max_proposals=max_proposals,
            )

            raw_json = advisor_service.run_agent(
                prompt, system_override=_SELL_SCAN_SYSTEM, max_rounds=12
            )
            logger.info("Sell scan raw response (%d chars): %r", len(raw_json or ""), (raw_json or "")[:300])
            if not raw_json or not raw_json.strip():
                logger.warning("Sell scan: Claude returned empty response")
                return None

            stripped = raw_json.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("```", 2)[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                stripped = stripped.rsplit("```", 1)[0].strip()

            start = stripped.find("{")
            end = stripped.rfind("}") + 1
            if start == -1 or end == 0:
                logger.warning("Sell scan: no JSON object found in response")
                return None

            parsed = json.loads(stripped[start:end])
            proposals: list[dict] = []
            expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

            # Build a map of held quantities for validation
            held_qty: dict[str, float] = {p["symbol"]: p["qty"] for p in positions}

            for p in parsed.get("proposals", []):
                sym = p.get("symbol", "").upper()
                qty = float(p.get("quantity") or 0)
                if qty < 1:
                    continue
                # Never propose more shares than held
                max_qty = held_qty.get(sym, 0)
                if max_qty <= 0:
                    logger.debug("Sell scan: skipping %s — not held", sym)
                    continue
                qty = min(qty, max_qty)

                proposals.append({
                    "id": str(uuid.uuid4()),
                    "symbol": sym,
                    "action": "SELL",
                    "quantity": float(qty),
                    "order_type": p.get("order_type", "LIMIT"),
                    "limit_price": p.get("limit_price"),
                    "reasoning": p.get("reasoning", ""),
                    "urgency": p.get("urgency", "MEDIUM"),
                    "status": "pending",
                    "approval_token": secrets.token_hex(32),
                    "denial_token": secrets.token_hex(32),
                    "token_expires_at": expires_at,
                })

            if not proposals:
                logger.info("Sell scan: no high-conviction exit candidates found")
                return None

            alert = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "alert_type": "SELL_SCAN",
                "flags": [],
                "claude_analysis": None,
                "proposals": proposals,
                "portfolio_value": portfolio_value,
                "status": "pending",
                "sms_sent": False,
                "email_sent": False,
            }
            self._store.save_alert(alert)
            logger.info("Sell scan: %d proposal(s) saved (alert %s)", len(proposals), alert["id"])
            return alert

        except Exception:
            logger.exception("Sell scan failed")
            return None

    def check_exit_targets(
        self,
        broker_service: SchwabBrokerService,
    ) -> list[dict]:
        """Check executed BUY proposals against current prices. Returns new SELL flag dicts."""
        try:
            targets = []
            for alert in self._store.load_all():
                for p in alert.get("proposals", []):
                    if (
                        p.get("action") == "BUY"
                        and p.get("status") == "executed"
                        and p.get("target_price")
                        and p.get("stop_price")
                        and not p.get("exit_alerted")
                    ):
                        targets.append(p)

            if not targets:
                return []

            symbols = list({p["symbol"] for p in targets})
            try:
                quotes = broker_service.get_quotes(symbols)
            except Exception:
                return []

            triggered = []
            for p in targets:
                sym = p["symbol"]
                q = (quotes.get(sym) or {})
                price = (q.get("quote") or q).get("lastPrice") or 0
                if not price:
                    continue

                target = float(p["target_price"])
                stop = float(p["stop_price"])
                entry = float(p.get("limit_price") or 0)
                if not entry:
                    continue

                pct = (price - entry) / entry * 100
                if price >= target:
                    triggered.append({
                        "symbol": sym, "current_price": price,
                        "entry_price": entry, "pct": pct,
                        "kind": "target",
                        "description": (
                            f"{sym} hit your +30% profit target at ${price:.2f} "
                            f"(bought @ ${entry:.2f}, up {pct:.1f}%). Consider taking profits."
                        ),
                    })
                    self._store.mark_exit_alerted(p["id"])
                elif price <= stop:
                    triggered.append({
                        "symbol": sym, "current_price": price,
                        "entry_price": entry, "pct": pct,
                        "kind": "stop",
                        "description": (
                            f"{sym} hit your stop-loss at ${price:.2f} "
                            f"(bought @ ${entry:.2f}, down {abs(pct):.1f}%). Consider cutting losses."
                        ),
                    })
                    self._store.mark_exit_alerted(p["id"])

            return triggered
        except Exception:
            logger.exception("Exit target check failed")
            return []
