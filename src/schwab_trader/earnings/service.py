"""Earnings calendar and pre-trade brief service."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# yfinance logs HTTP 404 errors at WARNING level when ETFs lack quoteSummary data.
# These are expected and noisy — suppress them.
logging.getLogger("yfinance").setLevel(logging.ERROR)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_earnings_calendar(symbols: list[str]) -> list[dict]:
    """Return upcoming earnings dates for the given symbols, sorted by proximity."""
    results = []
    today = date.today()

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            cal = ticker.calendar

            if cal is None:
                continue

            # yfinance returns a dict like {"Earnings Date": [Timestamp, ...], ...}
            raw_dates = cal.get("Earnings Date", [])
            if not raw_dates:
                continue

            # Take the first (earliest) date in the list
            raw = raw_dates[0] if isinstance(raw_dates, list) else raw_dates
            if isinstance(raw, datetime):
                earnings_date: date = raw.date()
            elif isinstance(raw, date):
                earnings_date = raw
            elif isinstance(raw, str):
                earnings_date = datetime.fromisoformat(raw).date()
            else:
                continue

            days_until = (earnings_date - today).days

            results.append({
                "symbol": sym,
                "date": earnings_date.isoformat(),
                "days_until": days_until,
                "is_soon": 0 <= days_until <= 14,
                "is_urgent": 0 <= days_until <= 7,
            })
        except Exception as exc:
            logger.debug("Earnings lookup failed for %s: %s", sym, exc)

    # Sort: upcoming first (smallest positive days_until), then past
    upcoming = sorted([r for r in results if r["days_until"] >= 0], key=lambda x: x["days_until"])
    past = sorted([r for r in results if r["days_until"] < 0], key=lambda x: -x["days_until"])
    return upcoming + past


def get_earnings_fundamentals(symbol: str) -> dict:
    """Fetch key fundamentals and earnings history for a pre-trade brief."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        # Earnings history: beat/miss pattern
        hist = ticker.earnings_history
        beat_miss: list[dict] = []
        if hist is not None and not hist.empty:
            for _, row in hist.tail(8).iterrows():
                eps_est = _safe_float(row.get("epsEstimate"))
                eps_act = _safe_float(row.get("epsActual"))
                surprise = _safe_float(row.get("epsDifference"))
                pct = _safe_float(row.get("surprisePercent"))
                beat_miss.append({
                    "date": str(row.name.date()) if hasattr(row.name, "date") else str(row.name),
                    "estimate": eps_est,
                    "actual": eps_act,
                    "surprise": surprise,
                    "surprise_pct": round(pct, 1),
                    "beat": eps_act >= eps_est if eps_est else None,
                })

        # Forward estimates
        estimates: dict = {}
        try:
            ee = ticker.earnings_estimate
            if ee is not None and not ee.empty and "0q" in ee.index:
                row = ee.loc["0q"]
                estimates = {
                    "avg": _safe_float(row.get("avg")),
                    "low": _safe_float(row.get("low")),
                    "high": _safe_float(row.get("high")),
                    "growth": _safe_float(row.get("yearAgoEps")),
                }
        except Exception:
            pass

        return {
            "symbol": symbol,
            "company_name": info.get("longName", symbol),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "analyst_target": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
            "beat_miss_history": beat_miss,
            "forward_estimates": estimates,
        }
    except Exception as exc:
        logger.warning("Fundamentals fetch failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}
