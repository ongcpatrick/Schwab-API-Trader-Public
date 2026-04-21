"""Thesis tracker — stores the original buy thesis for each executed proposal
and runs a weekly Claude check to assess whether it's still intact."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schwab_trader.advisor.service import AdvisorService
    from schwab_trader.agent.store import AlertStore
    from schwab_trader.broker.service import SchwabBrokerService

logger = logging.getLogger(__name__)

_STORE_PATH = Path(".data/thesis_log.json")

_CHECK_SYSTEM = (
    "You are a portfolio analyst checking whether an original buy thesis is still valid. "
    "Use get_stock_fundamentals, get_news, get_technical_indicators, and get_earnings_revisions "
    "to assess the current state of the position. Be direct and specific. No Markdown."
)

_CHECK_PROMPT = """Review this position and determine if the original buy thesis is still intact.

Symbol: {symbol}
Entry price: ${entry_price:.2f}
Current price: ${current_price:.2f} ({pnl_pct:+.1f}%)
Original thesis: {thesis}
Entered: {entry_date}

Steps:
1. Call get_stock_fundamentals(["{symbol}"]) — check revenue growth, margins, analyst target
2. Call get_news(["{symbol}"]) — any thesis-breaking news?
3. Call get_technical_indicators(["{symbol}"]) — is it still above the 200MA?
4. Call get_earnings_revisions(["{symbol}"]) — are analysts raising or cutting estimates?

Return ONLY valid JSON:
{{
  "symbol": "{symbol}",
  "status": "INTACT" | "WEAKENING" | "BROKEN",
  "confidence": 1-10,
  "notes": "2-3 sentences on current state vs original thesis",
  "action": "HOLD" | "TRIM" | "EXIT"
}}"""


def _load() -> dict:
    if _STORE_PATH.exists():
        try:
            return json.loads(_STORE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2))


def seed_from_alerts(alert_store: AlertStore) -> None:
    """Add any executed buy proposals that aren't yet in the thesis log."""
    log = _load()
    alerts = alert_store.load_all()
    changed = False

    for alert in alerts:
        for proposal in alert.get("proposals", []):
            if proposal.get("status") != "executed":
                continue
            if proposal.get("action", "BUY") != "BUY":
                continue
            sym = proposal.get("symbol")
            if not sym or sym in log:
                continue
            log[sym] = {
                "symbol": sym,
                "entry_price": proposal.get("limit_price") or proposal.get("estimated_price") or 0,
                "entry_date": proposal.get("executed_at", alert.get("timestamp", ""))[:10],
                "original_thesis": proposal.get("reasoning", ""),
                "status": "INTACT",
                "confidence": None,
                "notes": "Not yet reviewed.",
                "action": "HOLD",
                "last_checked": None,
                "history": [],
            }
            changed = True
            logger.info("ThesisTracker: seeded %s", sym)

    if changed:
        _save(log)


def check_all(
    broker_service: SchwabBrokerService,
    advisor_service: AdvisorService,
) -> list[dict]:
    """Run Claude thesis check for every tracked symbol still held in the portfolio.

    Returns list of updated thesis entries.
    """
    log = _load()
    if not log:
        return []

    # Get current portfolio to filter only still-held positions
    try:
        accounts = broker_service.get_accounts(fields=["positions"])
        positions = accounts[0].get("securitiesAccount", {}).get("positions", []) if accounts else []
        held = {p["instrument"]["symbol"]: p for p in positions}
    except Exception as exc:
        logger.warning("ThesisTracker: could not fetch portfolio: %s", exc)
        held = {}

    updated = []
    for sym, entry in list(log.items()):
        if sym not in held:
            continue  # position closed — skip

        pos = held[sym]
        last_price = float(pos.get("marketValue", 0)) / max(float(pos.get("longQuantity", 1)), 1)
        entry_price = float(entry.get("entry_price") or 0)
        pnl_pct = ((last_price - entry_price) / entry_price * 100) if entry_price else 0

        prompt = _CHECK_PROMPT.format(
            symbol=sym,
            entry_price=entry_price,
            current_price=last_price,
            pnl_pct=pnl_pct,
            thesis=entry.get("original_thesis", "No thesis recorded."),
            entry_date=entry.get("entry_date", "unknown"),
        )

        try:
            raw = advisor_service.run_agent(prompt, system_override=_CHECK_SYSTEM, max_rounds=8)
            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
        except Exception as exc:
            logger.warning("ThesisTracker: check failed for %s: %s", sym, exc)
            continue

        now = datetime.now(timezone.utc).isoformat()
        history_entry = {
            "checked_at": now,
            "status": result.get("status"),
            "confidence": result.get("confidence"),
            "notes": result.get("notes"),
            "action": result.get("action"),
            "price_at_check": round(last_price, 2),
        }

        log[sym] = {
            **entry,
            "status": result.get("status", entry["status"]),
            "confidence": result.get("confidence"),
            "notes": result.get("notes", ""),
            "action": result.get("action", "HOLD"),
            "last_checked": now,
            "history": [*entry.get("history", []), history_entry][-10:],  # keep last 10
        }
        updated.append(log[sym])
        logger.info("ThesisTracker: %s → %s (%s)", sym, log[sym]["status"], log[sym]["action"])

    _save(log)
    return updated


def get_all() -> list[dict]:
    """Return all thesis entries sorted by status severity."""
    log = _load()
    order = {"BROKEN": 0, "WEAKENING": 1, "INTACT": 2}
    return sorted(log.values(), key=lambda e: order.get(e.get("status", "INTACT"), 2))
