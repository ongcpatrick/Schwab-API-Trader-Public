"""Watchlist screener — pre-filters buy candidates before Claude analysis."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import yfinance as yf

from schwab_trader.broker.service import SchwabBrokerService

logger = logging.getLogger(__name__)

# Curated universe: semis, AI infra, high-growth tech, growth ETFs
WATCHLIST: list[str] = [
    # Semiconductors
    "NVDA", "AMD", "TSM", "AVGO", "QCOM", "MU", "AMAT", "KLAC", "LRCX", "ASML",
    "MRVL", "TXN", "ADI", "ON", "SWKS",
    # AI infrastructure / hyperscalers
    "MSFT", "GOOG", "META", "AMZN", "ORCL",
    # High-growth tech
    "PLTR", "CRWD", "APP", "NET", "DDOG", "ZS", "COIN", "TTD", "MNDY", "SNOW",
    # EV / future tech
    "TSLA", "RIVN",
    # Growth ETFs
    "SMH", "SOXX", "QQQ", "ARKK", "XLK", "SOXQ", "IGV",
]

_RECOMMENDATION_SCORE: dict[str, float] = {
    "strongbuy": 1.0,
    "buy": 0.75,
    "hold": 0.25,
    "underperform": 0.0,
    "sell": 0.0,
}


@dataclass
class ScreenedCandidate:
    symbol: str
    current_price: float
    change_1m_pct: float
    forward_pe: float | None
    revenue_growth: float | None
    analyst_target: float | None
    upside_pct: float | None
    recommendation: str | None
    score: float
    summary: str = field(default="")  # one-line formatted for Claude prompt


def _fetch_yf_info(sym: str) -> tuple[str, dict]:
    try:
        return sym, yf.Ticker(sym).info or {}
    except Exception:
        return sym, {}


def _compute_score(
    change_1m: float,
    upside_pct: float | None,
    revenue_growth: float | None,
    forward_pe: float | None,
    recommendation: str | None,
) -> float:
    """Weighted composite score — all sub-signals normalized to [0, 1]."""

    # Momentum: 1-month price change clipped to [-30%, +60%] → mapped to [0, 1]
    momentum = min(max((change_1m + 30) / 90, 0.0), 1.0)

    # Analyst upside: clipped to [0%, 60%] → [0, 1]
    upside_norm = min(max((upside_pct or 0) / 60, 0.0), 1.0)

    # Revenue growth: clipped to [0%, 80%] → [0, 1]
    growth_norm = min(max((revenue_growth or 0) * 100 / 80, 0.0), 1.0)

    # Valuation: lower forward P/E is better; fwdPE of 15 → 1.0, 60 → 0.0
    if forward_pe and forward_pe > 0:
        valuation = min(max(1 - (forward_pe - 15) / 45, 0.0), 1.0)
    else:
        valuation = 0.3  # neutral if no data

    # Analyst recommendation
    rec_key = (recommendation or "").lower().replace(" ", "")
    rec_norm = _RECOMMENDATION_SCORE.get(rec_key, 0.3)

    return round(
        0.30 * momentum
        + 0.20 * upside_norm
        + 0.20 * growth_norm
        + 0.15 * valuation
        + 0.15 * rec_norm,
        4,
    )


def screen_candidates(
    broker_service: SchwabBrokerService,
    *,
    excluded_symbols: set[str],
    top_n: int = 15,
    watchlist: list[str] | None = None,
) -> list[ScreenedCandidate]:
    """
    Screen the watchlist for buy candidates.

    1. Remove excluded symbols (already held or pending BUY proposal).
    2. Batch-fetch Schwab quotes for remaining symbols.
    3. Parallel-fetch yfinance info for fundamentals.
    4. Score each candidate; return top_n sorted descending.
    """
    universe = watchlist if watchlist else WATCHLIST
    candidates = [s for s in universe if s not in excluded_symbols]
    if not candidates:
        return []

    # --- Schwab quotes (single API call) ---
    quotes: dict = {}
    try:
        quotes = broker_service.get_quotes(candidates) or {}
    except Exception as exc:
        logger.warning("screen_candidates: get_quotes failed: %s", exc)

    # --- yfinance info (parallel) ---
    yf_info: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_yf_info, s): s for s in candidates}
        for fut in as_completed(futures):
            sym, info = fut.result()
            yf_info[sym] = info

    screened: list[ScreenedCandidate] = []
    for sym in candidates:
        q = quotes.get(sym, {}).get("quote", {})
        info = yf_info.get(sym, {})

        last = float(q.get("lastPrice") or q.get("mark") or 0)
        if last <= 0:
            continue

        w52_low = float(q.get("52WkLow") or 0)
        w52_high = float(q.get("52WkHigh") or last)
        change_1m = float(q.get("netPercentChangeInDouble") or 0)  # approximation

        target = info.get("targetMeanPrice")
        upside = round((target / last - 1) * 100, 1) if (target and last) else None
        fwd_pe = info.get("forwardPE")
        rev_growth = info.get("revenueGrowth")
        rec = info.get("recommendationKey")

        score = _compute_score(change_1m, upside, rev_growth, fwd_pe, rec)

        # Build one-line summary for Claude prompt
        parts = [f"{sym} | ${last:.2f}"]
        if w52_low and w52_high:
            pct_from_low = round((last - w52_low) / (w52_high - w52_low) * 100) if w52_high != w52_low else 0
            parts.append(f"52wk pos: {pct_from_low}%")
        if fwd_pe:
            parts.append(f"fwdPE: {fwd_pe:.1f}")
        if rev_growth:
            parts.append(f"rev_growth: {rev_growth * 100:.0f}%")
        if upside is not None:
            parts.append(f"target: ${target:.0f} ({upside:+.0f}%)")
        if rec:
            parts.append(f"rec: {rec}")
        parts.append(f"score: {score:.2f}")

        screened.append(ScreenedCandidate(
            symbol=sym,
            current_price=last,
            change_1m_pct=change_1m,
            forward_pe=fwd_pe,
            revenue_growth=rev_growth,
            analyst_target=target,
            upside_pct=upside,
            recommendation=rec,
            score=score,
            summary=" | ".join(parts),
        ))

    screened.sort(key=lambda c: c.score, reverse=True)
    return screened[:top_n]
