"""FRED (Federal Reserve Economic Data) service.

Fetches key macro indicators via the free FRED API.
API key is free at https://fred.stlouisfed.org/docs/api/api_key.html

Series used:
  DFF      - Effective Federal Funds Rate (daily)
  T10Y2Y   - 10-Year minus 2-Year Treasury spread (daily, recession signal)
  CPIAUCSL - CPI All Urban Consumers (monthly, YoY computed)
  PCEPI    - PCE Price Index (monthly, YoY computed)
  UNRATE   - Unemployment Rate (monthly)
  GS10     - 10-Year Treasury Constant Maturity Rate
  GS2      - 2-Year Treasury Constant Maturity Rate
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from datetime import datetime, timedelta

import certifi

logger = logging.getLogger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _fetch_series(api_key: str, series_id: str, limit: int = 13) -> list[dict]:
    """Fetch the most recent N observations for a FRED series."""
    url = (
        f"{_BASE}?series_id={series_id}"
        f"&api_key={api_key}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "schwab-ai-trader"})
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
        data = json.loads(resp.read())
    return data.get("observations", [])


def _latest_value(obs: list[dict]) -> float | None:
    """Return the most recent non-null observation value."""
    for o in obs:
        v = o.get("value", ".")
        if v != ".":
            try:
                return float(v)
            except ValueError:
                continue
    return None


def _yoy_pct(obs: list[dict]) -> float | None:
    """Compute YoY % change from monthly series (obs sorted desc, 13 obs = ~1yr)."""
    values = []
    for o in obs:
        v = o.get("value", ".")
        if v != ".":
            try:
                values.append(float(v))
            except ValueError:
                pass
        if len(values) == 13:
            break
    if len(values) >= 13:
        return round((values[0] / values[12] - 1) * 100, 2)
    return None


def get_macro_indicators(api_key: str) -> dict:
    """
    Fetch key FRED macro indicators. Returns a dict with:
      fed_funds_rate, t10y2y_spread, cpi_yoy, pce_yoy, unemployment,
      t10_yield, t2_yield, interpretation
    Returns empty dict (gracefully) if api_key is missing or request fails.
    """
    if not api_key:
        return {}

    results: dict = {}

    series_map = {
        "DFF": ("fed_funds_rate", "latest"),
        "T10Y2Y": ("t10y2y_spread", "latest"),
        "CPIAUCSL": ("cpi_yoy", "yoy"),
        "PCEPI": ("pce_yoy", "yoy"),
        "UNRATE": ("unemployment", "latest"),
        "GS10": ("t10_yield", "latest"),
        "GS2": ("t2_yield", "latest"),
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch(series_id: str) -> tuple[str, list[dict]]:
        try:
            limit = 13 if series_map[series_id][1] == "yoy" else 2
            return series_id, _fetch_series(api_key, series_id, limit=limit)
        except Exception as exc:
            logger.warning("FRED %s fetch failed: %s", series_id, exc)
            return series_id, []

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(_fetch, sid): sid for sid in series_map}
        raw: dict[str, list[dict]] = {}
        for fut in as_completed(futures):
            sid, obs = fut.result()
            raw[sid] = obs

    for series_id, (key, mode) in series_map.items():
        obs = raw.get(series_id, [])
        if mode == "yoy":
            results[key] = _yoy_pct(obs)
        else:
            results[key] = _latest_value(obs)

    # Derived signals
    fed = results.get("fed_funds_rate")
    spread = results.get("t10y2y_spread")
    cpi = results.get("cpi_yoy")
    unemp = results.get("unemployment")

    signals = []
    if fed is not None:
        if fed >= 5.0:
            signals.append(f"Fed funds {fed:.2f}% — restrictive policy")
        elif fed >= 3.0:
            signals.append(f"Fed funds {fed:.2f}% — moderately tight")
        else:
            signals.append(f"Fed funds {fed:.2f}% — accommodative")

    if spread is not None:
        if spread < 0:
            signals.append(f"Yield curve inverted ({spread:+.2f}%) — recession signal")
        elif spread < 0.3:
            signals.append(f"Yield curve flat ({spread:+.2f}%) — caution")
        else:
            signals.append(f"Yield curve normal ({spread:+.2f}%) — no inversion")

    if cpi is not None:
        if cpi > 4.0:
            signals.append(f"CPI {cpi:.1f}% YoY — elevated inflation")
        elif cpi > 2.5:
            signals.append(f"CPI {cpi:.1f}% YoY — above target")
        else:
            signals.append(f"CPI {cpi:.1f}% YoY — near target")

    results["signals"] = signals
    results["interpretation"] = " | ".join(signals) if signals else "FRED data unavailable"
    return results
