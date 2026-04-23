"""Watchlist screener — pre-filters buy candidates before Claude analysis."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import yfinance as yf

from schwab_trader.broker.service import SchwabBrokerService

logger = logging.getLogger(__name__)

# Curated seed list — high-conviction names the screener always considers,
# including growth stocks not yet in the S&P 500 (HIMS, AXON, COIN, etc.).
WATCHLIST: list[str] = [
    # Semiconductors
    "NVDA", "AMD", "TSM", "AVGO", "QCOM", "MU", "AMAT", "KLAC", "LRCX", "ASML",
    "MRVL", "TXN", "ADI", "ON", "SWKS",
    # Big tech & cloud
    "MSFT", "GOOG", "META", "AMZN", "ORCL", "AAPL", "CRM", "NOW", "ADBE",
    # High-growth SaaS / fintech
    "PLTR", "CRWD", "APP", "NET", "DDOG", "ZS", "COIN", "TTD", "MNDY", "SNOW",
    "AXON", "HIMS",
    # EV / mobility
    "TSLA",
    # Financials — wide-moat, capital-light
    "JPM", "V", "MA", "AXP", "GS", "BLK", "SCHW", "SPGI",
    # Healthcare — pharma + med devices
    "LLY", "NVO", "ABBV", "UNH", "ISRG", "TMO", "DXCM", "VEEV", "MRNA",
    # Consumer — durable brands
    "COST", "HD", "NKE", "SBUX", "BKNG",
    # Energy — quality operators
    "XOM", "CVX", "COP",
    # Industrials / defence
    "CAT", "DE", "RTX", "LMT", "GE",
    # Broad market & sector ETFs
    "SPY", "QQQ", "SMH", "SOXX", "XLK", "XLV", "XLF", "XLE", "XLI", "IGV",
]

# S&P 500 cache — refreshed at most once per hour
_sp500_cache: list[str] = []
_sp500_fetched_at: float = 0.0
_SP500_TTL = 3600.0


def _fetch_sp500_symbols() -> list[str]:
    """Return current S&P 500 tickers from Wikipedia, cached for 1 hour."""
    global _sp500_cache, _sp500_fetched_at
    if _sp500_cache and time.monotonic() - _sp500_fetched_at < _SP500_TTL:
        return _sp500_cache
    try:
        import io
        import ssl
        import urllib.request

        import pandas as pd

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            html = resp.read().decode("utf-8")
        table = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
        syms = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        _sp500_cache = syms
        _sp500_fetched_at = time.monotonic()
        logger.info("_fetch_sp500_symbols: loaded %d S&P 500 symbols", len(syms))
        return syms
    except Exception as exc:
        logger.warning("_fetch_sp500_symbols failed, using cache/watchlist: %s", exc)
        return _sp500_cache


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
    fcf_yield: float | None         # free cash flow yield — Morningstar quality signal
    return_on_equity: float | None  # ROE — wide-moat quality signal
    peg_ratio: float | None         # growth-adjusted valuation
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
    fcf_yield: float | None = None,
    return_on_equity: float | None = None,
) -> float:
    """Weighted composite score — all sub-signals normalized to [0, 1].

    Signals mirror Morningstar's quality screen:
      momentum + analyst upside + revenue growth + valuation (fwdPE) +
      FCF yield (cash generation quality) + ROE (moat proxy) + analyst rec.
    """
    # Momentum: 1-day price change clipped to [-30%, +60%] → [0, 1]
    momentum = min(max((change_1m + 30) / 90, 0.0), 1.0)

    # Analyst upside: clipped to [0%, 60%] → [0, 1]
    upside_norm = min(max((upside_pct or 0) / 60, 0.0), 1.0)

    # Revenue growth: clipped to [0%, 80%] → [0, 1]
    growth_norm = min(max((revenue_growth or 0) * 100 / 80, 0.0), 1.0)

    # Valuation: lower forward P/E is better; fwdPE 15 → 1.0, 60 → 0.0
    if forward_pe and forward_pe > 0:
        valuation = min(max(1 - (forward_pe - 15) / 45, 0.0), 1.0)
    else:
        valuation = 0.3  # neutral if no data

    # FCF yield: higher is better; 8%+ → 1.0, 0% → 0.0 (Morningstar quality gate)
    if fcf_yield and fcf_yield > 0:
        fcf_norm = min(fcf_yield / 0.08, 1.0)
    else:
        fcf_norm = 0.3  # neutral if no data

    # ROE: proxy for economic moat; 30%+ → 1.0, 0% → 0.0
    if return_on_equity and return_on_equity > 0:
        roe_norm = min(return_on_equity / 0.30, 1.0)
    else:
        roe_norm = 0.3  # neutral if no data

    # Analyst recommendation
    rec_key = (recommendation or "").lower().replace(" ", "")
    rec_norm = _RECOMMENDATION_SCORE.get(rec_key, 0.3)

    return round(
        0.25 * momentum
        + 0.15 * upside_norm
        + 0.15 * growth_norm
        + 0.15 * valuation
        + 0.15 * fcf_norm
        + 0.10 * roe_norm
        + 0.05 * rec_norm,
        4,
    )


def screen_candidates(
    broker_service: SchwabBrokerService,
    *,
    excluded_symbols: set[str],
    top_n: int = 15,
    watchlist: list[str] | None = None,
) -> list[ScreenedCandidate]:
    """Screen a broad universe for buy candidates.

    Pipeline:
    1. Build universe = curated watchlist + full S&P 500 (deduplicated).
    2. Remove excluded symbols (already held or pending proposal).
    3. Batch-fetch Schwab quotes — one API call for the whole universe.
    4. Pre-filter: keep only stocks with a valid price and sort by momentum.
       Take the top `top_n * 4` movers for deep fundamental analysis.
       This avoids calling yfinance for 500+ tickers every scan.
    5. Parallel-fetch yfinance fundamentals for the momentum shortlist.
    6. Score each candidate; return top_n sorted descending.
    """
    # --- Build universe: seed watchlist + S&P 500 ---
    seed = watchlist if watchlist else WATCHLIST
    sp500 = _fetch_sp500_symbols()
    # Preserve seed order, then append any S&P 500 names not already in seed
    seen: set[str] = set(seed)
    universe = list(seed)
    for sym in sp500:
        if sym not in seen:
            seen.add(sym)
            universe.append(sym)

    candidates = [s for s in universe if s not in excluded_symbols]
    if not candidates:
        return []

    logger.info("screen_candidates: universe=%d after exclusions", len(candidates))

    # --- Schwab batch quotes (single API call) ---
    # Schwab accepts up to 500 symbols per request; chunk if needed.
    quotes: dict = {}
    chunk_size = 400
    for i in range(0, len(candidates), chunk_size):
        chunk = candidates[i: i + chunk_size]
        try:
            chunk_quotes = broker_service.get_quotes(chunk) or {}
            quotes.update(chunk_quotes)
        except Exception as exc:
            logger.warning("screen_candidates: get_quotes chunk failed: %s", exc)

    # --- Momentum pre-filter ---
    # Sort all symbols with a valid last price by 1-day momentum descending.
    # Keep top `top_n * 4` for deep yfinance analysis to bound scan time.
    priced: list[tuple[str, float, float]] = []  # (sym, last, change_1d)
    for sym in candidates:
        q = quotes.get(sym, {}).get("quote", {})
        last = float(q.get("lastPrice") or q.get("mark") or 0)
        if last <= 0:
            continue
        change_1d = float(q.get("netPercentChangeInDouble") or 0)
        priced.append((sym, last, change_1d))

    # Sort by absolute momentum (capture both strong up and down-reversal candidates)
    priced.sort(key=lambda x: x[2], reverse=True)
    deep_list = priced[: top_n * 4]

    logger.info(
        "screen_candidates: %d priced symbols → deep analysis on top %d by momentum",
        len(priced),
        len(deep_list),
    )

    # --- yfinance fundamentals (parallel, bounded set) ---
    deep_syms = [sym for sym, _, _ in deep_list]
    yf_info: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_yf_info, s): s for s in deep_syms}
        for fut in as_completed(futures):
            sym, info = fut.result()
            yf_info[sym] = info

    # --- Score and build candidates ---
    screened: list[ScreenedCandidate] = []
    for sym, last, change_1d in deep_list:
        q = quotes.get(sym, {}).get("quote", {})
        info = yf_info.get(sym, {})

        w52_low = float(q.get("52WkLow") or 0)
        w52_high = float(q.get("52WkHigh") or last)

        target = info.get("targetMeanPrice")
        upside = round((target / last - 1) * 100, 1) if (target and last) else None
        fwd_pe = info.get("forwardPE")
        rev_growth = info.get("revenueGrowth")
        rec = info.get("recommendationKey")
        peg = info.get("pegRatio")

        market_cap = float(info.get("marketCap") or 0)
        free_cashflow = float(info.get("freeCashflow") or 0)
        fcf_yield = (free_cashflow / market_cap) if (market_cap > 0 and free_cashflow > 0) else None
        roe = info.get("returnOnEquity")

        # Skip micro-caps (< $2B market cap) — too illiquid for our order sizes
        if market_cap and market_cap < 2_000_000_000:
            continue

        score = _compute_score(change_1d, upside, rev_growth, fwd_pe, rec, fcf_yield, roe)

        parts = [f"{sym} | ${last:.2f}"]
        if w52_low and w52_high and w52_high != w52_low:
            pct_from_low = round((last - w52_low) / (w52_high - w52_low) * 100)
            parts.append(f"52wk pos: {pct_from_low}%")
        if market_cap:
            parts.append(f"mktcap: ${market_cap/1e9:.0f}B")
        if fwd_pe:
            parts.append(f"fwdPE: {fwd_pe:.1f}")
        if peg and peg > 0:
            parts.append(f"PEG: {peg:.2f}")
        if rev_growth:
            parts.append(f"rev_growth: {rev_growth * 100:.0f}%")
        if fcf_yield is not None:
            parts.append(f"FCF_yield: {fcf_yield * 100:.1f}%")
        if roe is not None:
            parts.append(f"ROE: {roe * 100:.0f}%")
        if upside is not None:
            parts.append(f"target: ${target:.0f} ({upside:+.0f}%)")
        if rec:
            parts.append(f"rec: {rec}")
        parts.append(f"score: {score:.2f}")

        screened.append(ScreenedCandidate(
            symbol=sym,
            current_price=last,
            change_1m_pct=change_1d,
            forward_pe=fwd_pe,
            revenue_growth=rev_growth,
            analyst_target=target,
            upside_pct=upside,
            recommendation=rec,
            fcf_yield=fcf_yield,
            return_on_equity=roe,
            peg_ratio=peg,
            score=score,
            summary=" | ".join(parts),
        ))

    screened.sort(key=lambda c: c.score, reverse=True)
    logger.info("screen_candidates: returning top %d of %d scored", top_n, len(screened))
    return screened[:top_n]
