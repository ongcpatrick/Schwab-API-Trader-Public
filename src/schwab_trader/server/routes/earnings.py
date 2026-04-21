"""Earnings calendar and AI pre-trade brief routes."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from schwab_trader.advisor.service import AdvisorService
from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.core.settings import get_settings
import yfinance as yf

from schwab_trader.earnings.service import get_earnings_calendar, get_earnings_fundamentals
from schwab_trader.server.dependencies import get_broker_service

router = APIRouter()

_BRIEF_PROMPT = """You are preparing a pre-earnings briefing for {symbol} ({company}).

POSITION:
{position_block}

EARNINGS IN {days_until} DAYS ({earnings_date})

FUNDAMENTALS:
- Sector: {sector} | Industry: {industry}
- P/E: {pe} | Forward P/E: {fpe} | PEG: {peg}
- Revenue Growth: {rev_growth} | Earnings Growth: {earn_growth}
- Profit Margin: {margin}
- Analyst Target: {target} | Consensus: {rec}

RECENT EARNINGS HISTORY (beat / miss):
{history_block}

FORWARD ESTIMATE THIS QUARTER:
{estimate_block}

Write a sharp pre-earnings brief covering:
1. **What to watch** — the 2-3 metrics that will move the stock
2. **Bull / Bear case** — what good and bad results look like
3. **Position sizing** — given the position size and days until earnings, should they hold, trim, or add?
4. **Risk** — what could surprise (positively or negatively)?

Be specific with numbers. Max 250 words."""


def _build_position_block(symbol: str, positions: list[dict]) -> str:
    for p in positions:
        if p.get("instrument", {}).get("symbol") == symbol:
            qty = p.get("longQuantity", 0)
            avg = p.get("averagePrice", 0)
            mkt = p.get("marketValue", 0)
            cost = qty * avg
            pnl = mkt - cost
            pct = (pnl / cost * 100) if cost else 0
            return (
                f"{qty:.4f} shares @ avg ${avg:.2f} | "
                f"Market value ${mkt:,.2f} | "
                f"P&L ${pnl:+,.2f} ({pct:+.1f}%)"
            )
    return "No position held."


def _build_history_block(history: list[dict]) -> str:
    if not history:
        return "No history available."
    lines = []
    for h in history[-5:]:
        beat = "BEAT" if h.get("beat") else ("MISS" if h.get("beat") is False else "?")
        lines.append(
            f"  {h['date']}: Est ${h['estimate']:.2f} → Act ${h['actual']:.2f} "
            f"({h['surprise_pct']:+.1f}%) [{beat}]"
        )
    return "\n".join(lines)


def _build_estimate_block(est: dict) -> str:
    if not est:
        return "No estimate available."
    return (
        f"Avg ${est.get('avg', 0):.2f} | "
        f"Range ${est.get('low', 0):.2f}–${est.get('high', 0):.2f}"
    )


def _pct_str(val) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val) * 100:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt(val, prefix="", suffix="", decimals=2) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{prefix}{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def get_advisor(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> AdvisorService:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY not configured.",
        )
    return AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)


@router.get("/calendar")
def earnings_calendar(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> list[dict]:
    """Return upcoming earnings dates for all held symbols."""
    accounts = broker_service.get_accounts(fields=["positions"])
    if not accounts:
        return []
    positions = accounts[0].get("securitiesAccount", {}).get("positions", [])
    symbols = [
        p["instrument"]["symbol"]
        for p in positions
        if p.get("instrument", {}).get("assetType") == "EQUITY"
    ]
    return get_earnings_calendar(symbols)


@router.get("/brief/{symbol}")
def earnings_brief(
    symbol: str,
    advisor: Annotated[AdvisorService, Depends(get_advisor)],
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> StreamingResponse:
    """Stream a Claude pre-earnings brief for a symbol."""
    # Get live positions for position context
    accounts = broker_service.get_accounts(fields=["positions"])
    positions = accounts[0].get("securitiesAccount", {}).get("positions", []) if accounts else []

    # Get earnings date
    cal = get_earnings_calendar([symbol])
    earnings_entry = next((e for e in cal if e["symbol"] == symbol), {})
    days_until = earnings_entry.get("days_until", "?")
    earnings_date = earnings_entry.get("date", "unknown")

    # Get fundamentals
    fund = get_earnings_fundamentals(symbol)

    prompt = _BRIEF_PROMPT.format(
        symbol=symbol,
        company=fund.get("company_name", symbol),
        position_block=_build_position_block(symbol, positions),
        days_until=days_until,
        earnings_date=earnings_date,
        sector=fund.get("sector", "N/A"),
        industry=fund.get("industry", "N/A"),
        pe=_fmt(fund.get("pe_ratio"), decimals=1),
        fpe=_fmt(fund.get("forward_pe"), decimals=1),
        peg=_fmt(fund.get("peg_ratio"), decimals=2),
        rev_growth=_pct_str(fund.get("revenue_growth")),
        earn_growth=_pct_str(fund.get("earnings_growth")),
        margin=_pct_str(fund.get("profit_margin")),
        target=_fmt(fund.get("analyst_target"), prefix="$", decimals=2),
        rec=(fund.get("recommendation") or "N/A").upper(),
        history_block=_build_history_block(fund.get("beat_miss_history", [])),
        estimate_block=_build_estimate_block(fund.get("forward_estimates", {})),
    )

    def generate():
        try:
            for chunk in advisor.stream_chat(prompt, [], ""):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/fundamentals/{symbol}")
def fundamentals(symbol: str) -> dict:
    """Return key fundamentals for a symbol."""
    return get_earnings_fundamentals(symbol.upper())


@router.get("/sectors")
def earnings_sectors(symbols: str) -> dict:
    """Return sector mapping for a comma-separated list of symbols."""
    result: dict[str, str] = {}
    for sym in symbols.split(","):
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            info = yf.Ticker(sym).info or {}
            result[sym] = info.get("sector") or "Unknown"
        except Exception:
            result[sym] = "Unknown"
    return result
