"""Intermarket regime detection — classifies the current market environment.

Uses cross-asset signals (SPY, TLT, HYG, GLD, IWM, UUP, VIX) sourced via
yfinance to classify the macro regime. The result gates the buy-scan agent:
BEAR and RISK_OFF regimes suppress new long proposals.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("./.data/regime.json")
_CACHE_TTL_HOURS = 4  # refresh at most every 4 hours


class Regime(str, Enum):
    BULL = "BULL"            # trending up, low vol, broad participation
    RECOVERY = "RECOVERY"    # above SMA200 but vol elevated or breadth lagging
    CORRECTION = "CORRECTION"  # short-term pullback within longer uptrend
    BEAR = "BEAR"            # below SMA200, momentum negative, high vol
    RISK_OFF = "RISK_OFF"    # credit stress + safe-haven demand + high VIX
    STAGFLATION = "STAGFLATION"  # dollar strong, breadth weak, credit weak
    UNKNOWN = "UNKNOWN"      # data unavailable — treated as neutral


def detect_regime() -> Regime:
    """Return the current market regime, using a 4-hour file cache."""
    cached = _load_cache()
    if cached is not None:
        return cached

    try:
        regime = _compute_regime()
    except Exception:
        logger.exception("Regime detection failed; defaulting to UNKNOWN")
        regime = Regime.UNKNOWN

    _save_cache(regime)
    return regime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_cache() -> Regime | None:
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            cached_at = datetime.fromisoformat(data["cached_at"])
            if datetime.now(UTC) - cached_at < timedelta(hours=_CACHE_TTL_HOURS):
                return Regime(data["regime"])
    except Exception:
        pass
    return None


def _save_cache(regime: Regime) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps({
            "regime": regime.value,
            "cached_at": datetime.now(UTC).isoformat(),
        }))
    except Exception:
        logger.warning("Could not persist regime cache to %s", _CACHE_PATH)


def _safe_float(series, idx: int) -> float | None:
    try:
        v = series.iloc[idx]
        return float(v) if v is not None else None
    except Exception:
        return None


def _compute_regime() -> Regime:
    """Download ~1 year of price history and compute cross-asset signals."""
    import pandas as pd  # already in deps via yfinance

    tickers = ["SPY", "TLT", "HYG", "GLD", "IWM", "UUP", "^VIX"]
    raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False)

    # yfinance returns multi-level columns when >1 ticker
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]]

    def col(sym: str):
        return close[sym].dropna()

    spy = col("SPY")
    tlt = col("TLT")
    hyg = col("HYG")
    gld = col("GLD")
    iwm = col("IWM")
    uup = col("UUP")
    vix = col("^VIX")

    if len(spy) < 50:
        logger.warning("Insufficient price history for regime detection")
        return Regime.UNKNOWN

    # 1. SPY trend — price vs 200-day SMA (fraction above/below)
    sma200 = spy.rolling(200).mean()
    spy_sma200 = _safe_float(sma200.dropna(), -1)
    spy_last = _safe_float(spy, -1)
    spy_trend = ((spy_last / spy_sma200) - 1.0) if spy_sma200 and spy_last else 0.0

    # 2. SPY momentum — 20-day rate of change
    spy_20ago = _safe_float(spy, -20) if len(spy) >= 20 else None
    spy_mom = ((spy_last / spy_20ago) - 1.0) if spy_20ago and spy_last else 0.0

    # 3. Credit stress — HYG/TLT ratio vs its own 20-day mean (negative = stress)
    credit_ratio = hyg / tlt
    credit_last = _safe_float(credit_ratio, -1)
    credit_ma = _safe_float(credit_ratio.rolling(20).mean().dropna(), -1)
    credit_signal = ((credit_last / credit_ma) - 1.0) if credit_ma and credit_last else 0.0

    # 4. Safe-haven demand — GLD vs 50-day SMA
    gld_sma50 = _safe_float(gld.rolling(50).mean().dropna(), -1)
    gld_last = _safe_float(gld, -1)
    gld_signal = ((gld_last / gld_sma50) - 1.0) if gld_sma50 and gld_last else 0.0

    # 5. Breadth — IWM/SPY relative ratio vs 20-day mean
    breadth = iwm / spy
    breadth_last = _safe_float(breadth, -1)
    breadth_ma = _safe_float(breadth.rolling(20).mean().dropna(), -1)
    breadth_signal = ((breadth_last / breadth_ma) - 1.0) if breadth_ma and breadth_last else 0.0

    # 6. Dollar — UUP vs 20-day SMA
    uup_sma20 = _safe_float(uup.rolling(20).mean().dropna(), -1)
    uup_last = _safe_float(uup, -1)
    dollar_signal = ((uup_last / uup_sma20) - 1.0) if uup_sma20 and uup_last else 0.0

    # 7. VIX level
    vix_level = _safe_float(vix, -1) or 20.0

    logger.info(
        "Regime signals — spy_trend: %.3f  spy_mom: %.3f  credit: %.3f  "
        "gld: %.3f  breadth: %.3f  dollar: %.3f  vix: %.1f",
        spy_trend, spy_mom, credit_signal,
        gld_signal, breadth_signal, dollar_signal, vix_level,
    )

    # --- Classification (ordered most-severe → least-severe) ---

    # BEAR: SPY deep below SMA200 or violent momentum collapse + panic VIX
    if spy_trend < -0.10 or (spy_mom < -0.05 and vix_level > 30):
        return Regime.BEAR

    # RISK_OFF: credit stress + safe-haven demand + elevated VIX
    if credit_signal < -0.02 and vix_level > 25 and gld_signal > 0.01:
        return Regime.RISK_OFF

    # STAGFLATION: dollar strong, small-cap breadth poor, slight downtrend
    if dollar_signal > 0.01 and breadth_signal < -0.01 and spy_trend < 0.02:
        return Regime.STAGFLATION

    # CORRECTION: SPY modestly below SMA200 or short-term momentum weak
    if spy_trend < -0.03 or (spy_mom < -0.02 and vix_level > 20):
        return Regime.CORRECTION

    # RECOVERY: above SMA200 but vol still elevated or breadth lagging
    if spy_trend > 0 and (vix_level > 22 or breadth_signal < -0.01):
        return Regime.RECOVERY

    # BULL: strong trend, low vol, broad participation
    return Regime.BULL
