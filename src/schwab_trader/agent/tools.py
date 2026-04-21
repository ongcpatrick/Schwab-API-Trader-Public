"""Claude tool schemas and executor for live portfolio intelligence."""

from __future__ import annotations

import json
import logging
import re as _re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


def _sanitize(text: str | None, max_len: int = 500) -> str:
    """Strip prompt-injection vectors from external text before passing to Claude.

    Removes:
    - Control characters and null bytes (C0/C1 range except normal whitespace)
    - XML/HTML tags that could hijack system prompt parsing
    - Null bytes and Unicode direction-override chars
    Truncates to max_len characters.
    """
    if not text:
        return ""
    # Strip null bytes and Unicode control chars (keep tab, newline, carriage return)
    text = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\ufeff]", "", text)
    # Strip XML/HTML tags
    text = _re.sub(r"<[^>]{0,200}>", "", text)
    # Truncate
    return text[:max_len]

import pandas as pd
import yfinance as yf

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.earnings.service import get_earnings_calendar, get_earnings_fundamentals
from schwab_trader.news.service import get_news_feed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas (Anthropic tool format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_portfolio",
        "description": (
            "Fetch live portfolio positions and account balances from Schwab. "
            "Returns current holdings with shares, average cost, market value, "
            "day P&L, and total P&L. Call this before any portfolio analysis — do not "
            "estimate holdings from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Get OHLCV price history for a stock symbol. "
            "Useful for identifying trends, support/resistance levels, and recent volatility. "
            "Do NOT call this for multiple symbols in a loop — call it once per symbol needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": (
                        "Uppercase stock ticker symbol. "
                        "Examples: 'AAPL', 'NVDA', 'QQQ'"
                    ),
                },
                "period_type": {
                    "type": "string",
                    "enum": ["day", "month", "year", "ytd"],
                    "description": (
                        "Time period bucket. Use 'month' for recent trend (default), "
                        "'year' for long-term view, 'ytd' for year-to-date."
                    ),
                },
                "period": {
                    "type": "integer",
                    "description": (
                        "Number of period_type units to look back. "
                        "Examples: period_type='month', period=3 → last 3 months. "
                        "period_type='year', period=1 → last 12 months. Default: 1."
                    ),
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_news",
        "description": (
            "Fetch recent news headlines for one or more stock symbols. "
            "Each headline includes a severity rating (HIGH/MEDIUM/LOW) and "
            "a short analyst take on market impact. "
            "Pass all symbols in a single call — do not call once per symbol."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Uppercase ticker symbols. "
                        "Example: [\"NVDA\", \"AMD\", \"TSM\"]"
                    ),
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_earnings_calendar",
        "description": (
            "Get upcoming earnings dates and key fundamentals for stock symbols. "
            "Includes days until earnings, P/E ratio, revenue growth, and analyst targets. "
            "Use this to check if earnings are imminent before recommending a trade."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Uppercase ticker symbols. "
                        "Example: [\"AAPL\", \"MSFT\", \"GOOGL\"]"
                    ),
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_stock_fundamentals",
        "description": (
            "Fetch current price, key fundamentals, and analyst data for a list of stock symbols. "
            "Returns price, 52-week range, PE ratio, forward PE, PEG ratio, revenue growth, "
            "earnings growth, profit margin, analyst target price, upside %, recommendation, "
            "short interest %, Piotroski F-score, and Altman Z-score. "
            "Use this when evaluating buy candidates outside the current portfolio. "
            "Pass all symbols in one call — results are fetched in parallel."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Uppercase ticker symbols to evaluate. "
                        "Example: [\"NVDA\", \"AMD\", \"AVGO\", \"TSM\"]"
                    ),
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Get RSI-14, 50-day MA, and 200-day MA for a list of symbols. "
            "Use to assess entry timing — is the stock oversold and above its long-term trend? "
            "RSI < 30 = oversold (potential entry), RSI > 70 = overbought (wait). "
            "Being above the 200-day MA confirms the long-term uptrend. "
            "Pass all symbols in one call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Uppercase ticker symbols. Example: [\"NVDA\", \"AMD\"]",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_insider_activity",
        "description": (
            "Check corporate insider buying (executives, directors purchasing their own stock) "
            "AND congressional/senate stock purchases (STOCK Act disclosures) in the last 90 days. "
            "Insider buying by a CEO or CFO is one of the strongest buy signals. "
            "Congressional purchases (Pelosi, etc.) often precede policy-related moves. "
            "Pass all symbols in one call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Uppercase ticker symbols. Example: [\"NVDA\", \"AMD\", \"AVGO\"]",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_earnings_revisions",
        "description": (
            "Get EPS estimate revision trends for a list of symbols — are analysts raising or "
            "cutting their earnings forecasts? Rising revisions (analysts upgrading estimates) "
            "is one of the strongest leading indicators of stock outperformance. "
            "Cutting revisions is a warning sign. Pass all symbols in one call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Uppercase ticker symbols. Example: [\"NVDA\", \"AMD\", \"AVGO\"]",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_macro_context",
        "description": (
            "Get current macro market conditions: VIX fear gauge, SPY and QQQ vs their 200-day MA, "
            "sector ETF performance (XLK, SMH, XLE, XLF, XLV, XLY), and a market regime signal. "
            "Call this FIRST before any buy scan to know if it's safe to buy or if the market "
            "is in a risk-off environment. No parameters needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class ToolExecutor:
    """Executes tool calls on behalf of the Claude agent."""

    def __init__(self, broker_service: SchwabBrokerService) -> None:
        self._broker = broker_service

    def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Dispatch a named tool call and return a JSON string result."""
        try:
            if name == "get_portfolio":
                return self.get_portfolio()
            if name == "get_price_history":
                return self.get_price_history(**tool_input)
            if name == "get_news":
                return self.get_news(**tool_input)
            if name == "get_earnings_calendar":
                return self.get_earnings_calendar(**tool_input)
            if name == "get_stock_fundamentals":
                return self.get_stock_fundamentals(**tool_input)
            if name == "get_technical_indicators":
                return self.get_technical_indicators(**tool_input)
            if name == "get_insider_activity":
                return self.get_insider_activity(**tool_input)
            if name == "get_earnings_revisions":
                return self.get_earnings_revisions(**tool_input)
            if name == "get_macro_context":
                return self.get_macro_context()
            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as exc:
            logger.warning("Tool %s failed: %s", name, exc)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def get_portfolio(self) -> str:
        accounts = self._broker.get_accounts(fields=["positions"])
        if not accounts:
            return json.dumps({"error": "No accounts found"})

        acct = accounts[0].get("securitiesAccount", {})
        bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
        positions = acct.get("positions", [])

        holdings = []
        for p in sorted(positions, key=lambda x: x.get("marketValue", 0), reverse=True):
            inst = p.get("instrument", {})
            sym = inst.get("symbol", "?")
            qty = (p.get("longQuantity") or 0) - (p.get("shortQuantity") or 0)
            avg = p.get("averagePrice") or 0
            mkt = p.get("marketValue") or 0
            cost = abs(qty) * avg
            total_pnl = mkt - cost
            total_pct = (total_pnl / cost * 100) if cost else 0
            holdings.append({
                "symbol": sym,
                "qty": round(qty, 4),
                "avg_cost": round(avg, 2),
                "market_value": round(mkt, 2),
                "cost_basis": round(cost, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pct": round(total_pct, 1),
                "day_pnl": round(p.get("currentDayProfitLoss") or 0, 2),
                "day_pct": round(p.get("currentDayProfitLossPercentage") or 0, 2),
            })

        return json.dumps({
            "portfolio_value": round(float(bal.get("liquidationValue") or 0), 2),
            "cash": round(float(bal.get("cashAvailableForTrading") or 0), 2),
            "positions": holdings,
        })

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "month",
        period: int = 1,
    ) -> str:
        data = self._broker.get_price_history(
            symbol,
            period_type=period_type,
            period=period,
            frequency_type="daily",
            frequency=1,
        )
        candles = data.get("candles", [])[-30:]  # cap at 30 most recent candles
        if not candles:
            return json.dumps({"symbol": symbol, "error": "No price data available"})

        first, last = candles[0], candles[-1]
        change_pct = (
            (last["close"] - first["open"]) / first["open"] * 100 if first["open"] else 0
        )
        return json.dumps({
            "symbol": symbol,
            "period": f"{period} {period_type}",
            "current_price": last["close"],
            "open_price": first["open"],
            "change_pct": round(change_pct, 2),
            "period_high": max(c["high"] for c in candles),
            "period_low": min(c["low"] for c in candles),
            "candles": candles,
        })

    def get_news(self, symbols: list[str]) -> str:
        items = get_news_feed(symbols, max_per_symbol=4)
        simplified = [
            {
                "symbol": it["symbol"],
                "title": _sanitize(it["title"], 200),
                "publisher": _sanitize(it["publisher"], 80),
                "published": it["published_str"],
                "material": it["material"],
                "severity": it["severity"],
                "take": _sanitize(it["take"], 300),
            }
            for it in items[:20]
        ]
        return json.dumps({"news": simplified})

    def get_earnings_calendar(self, symbols: list[str]) -> str:
        calendar = get_earnings_calendar(symbols)
        enriched = []
        for entry in calendar:
            fund = get_earnings_fundamentals(entry["symbol"])
            enriched.append({**entry, "fundamentals": fund})
        return json.dumps({"earnings": enriched})

    def get_stock_fundamentals(self, symbols: list[str]) -> str:
        """Merge Schwab quotes + yfinance info/financials for each symbol (parallelized)."""
        # Single Schwab API call for all quotes
        quotes: dict = {}
        try:
            raw = self._broker.get_quotes(symbols) or {}
            quotes = raw
        except Exception as exc:
            logger.warning("get_quotes failed: %s", exc)

        # Parallel yfinance fetches — info + balance sheet + cashflow + income
        def _fetch_ticker_data(sym: str) -> tuple[str, dict, Any, Any, Any]:
            try:
                t = yf.Ticker(sym)
                info = t.info or {}
                bs = t.balance_sheet
                cf = t.cashflow
                inc = t.income_stmt
                return sym, info, bs, cf, inc
            except Exception:
                return sym, {}, None, None, None

        ticker_data: dict[str, tuple] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_ticker_data, s): s for s in symbols}
            for fut in as_completed(futures):
                sym, info, bs, cf, inc = fut.result()
                ticker_data[sym] = (info, bs, cf, inc)

        results = []
        for sym in symbols:
            q = quotes.get(sym, {}).get("quote", {})
            info, bs, cf, inc = ticker_data.get(sym, ({}, None, None, None))
            last = float(q.get("lastPrice") or q.get("mark") or 0)
            target = info.get("targetMeanPrice")
            upside = round((target / last - 1) * 100, 1) if (target and last) else None
            market_cap = info.get("marketCap")

            piotroski = _piotroski_f_score(bs, cf, inc)
            altman_z, altman_zone = _altman_z_score(bs, inc, market_cap)

            results.append({
                "symbol": sym,
                "last_price": last,
                "week52_high": q.get("52WkHigh"),
                "week52_low": q.get("52WkLow"),
                "pe_ratio": q.get("peRatio") or info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "profit_margin": info.get("profitMargins"),
                "analyst_target": target,
                "analyst_upside_pct": upside,
                "recommendation": info.get("recommendationKey"),
                "sector": info.get("sector"),
                "short_interest_pct": info.get("shortPercentOfFloat"),
                "piotroski_f": piotroski,
                "altman_z": altman_z,
                "altman_zone": altman_zone,
            })
        return json.dumps({"fundamentals": results})

    def get_technical_indicators(self, symbols: list[str]) -> str:
        """RSI-14 and 200-day moving average for each symbol."""

        def _compute(sym: str) -> tuple[str, dict]:
            try:
                hist = yf.Ticker(sym).history(period="1y")
                if hist.empty or len(hist) < 15:
                    return sym, {"error": "insufficient price history"}
                closes = hist["Close"]
                current = float(closes.iloc[-1])

                # 200-day MA (use all available data up to 200 bars)
                window = min(200, len(closes))
                ma200 = float(closes.rolling(window).mean().iloc[-1])
                pct_vs_ma200 = round((current / ma200 - 1) * 100, 1) if ma200 else None

                # RSI-14
                delta = closes.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, float("nan"))
                rsi = float((100 - (100 / (1 + rs))).iloc[-1])
                rsi_signal = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral"

                # 50-day MA for shorter-term trend context
                ma50 = float(closes.rolling(min(50, len(closes))).mean().iloc[-1])

                return sym, {
                    "current_price": round(current, 2),
                    "ma_50": round(ma50, 2),
                    "ma_200": round(ma200, 2),
                    "pct_vs_ma200": pct_vs_ma200,
                    "is_above_200ma": current > ma200,
                    "is_above_50ma": current > ma50,
                    "rsi_14": round(rsi, 1),
                    "rsi_signal": rsi_signal,
                }
            except Exception as exc:
                return sym, {"error": str(exc)}

        results: dict = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_compute, s): s for s in symbols}
            for fut in as_completed(futures):
                sym, data = fut.result()
                results[sym] = data
        return json.dumps({"technicals": results})

    def get_insider_activity(self, symbols: list[str]) -> str:
        """Corporate insider buys (SEC EDGAR Form 4) + congressional trades (House/Senate STOCK Act disclosures)."""
        import urllib.request
        from datetime import datetime, timedelta

        symbol_set = {s.upper() for s in symbols}
        cutoff_dt = datetime.now() - timedelta(days=90)

        # --- Corporate insiders via SEC EDGAR Form 4 (primary source) ---
        insider_map: dict[str, list] = {}
        try:
            from schwab_trader.edgar.service import get_form4_trades
            edgar_results = get_form4_trades(list(symbol_set), days=90)
            for sym, trades in edgar_results.items():
                insider_map[sym] = [
                    {
                        "insider": _sanitize(t.get("insider", ""), 80),
                        "title": _sanitize(t.get("title", ""), 60),
                        "date": t.get("date", ""),
                        "shares": t.get("shares", 0),
                        "value": t.get("value", 0),
                        "price": t.get("price", 0),
                        "source": "SEC EDGAR Form 4",
                    }
                    for t in trades
                ]
        except Exception as exc:
            logger.warning("EDGAR Form 4 fetch failed, falling back to yfinance: %s", exc)
            # Fallback: yfinance insider transactions
            def _fetch_insider_yf(sym: str) -> tuple[str, list[dict]]:
                trades: list[dict] = []
                try:
                    df = yf.Ticker(sym).insider_transactions
                    if df is None or df.empty:
                        return sym, trades
                    for _, row in df.iterrows():
                        tx_date = row.get("Start Date") or row.get("startDate")
                        if tx_date is None:
                            continue
                        if hasattr(tx_date, "to_pydatetime"):
                            tx_date = tx_date.to_pydatetime().replace(tzinfo=None)
                        if isinstance(tx_date, str):
                            try:
                                tx_date = datetime.strptime(tx_date[:10], "%Y-%m-%d")
                            except Exception:
                                continue
                        if tx_date < cutoff_dt:
                            continue
                        text = str(row.get("Text") or row.get("text") or "")
                        if "sale" in text.lower() or "sell" in text.lower():
                            continue
                        trades.append({
                            "insider": _sanitize(str(row.get("Insider") or row.get("insider") or ""), 80),
                            "title": _sanitize(str(row.get("Relationship") or row.get("relationship") or ""), 60),
                            "date": tx_date.strftime("%Y-%m-%d"),
                            "shares": int(row.get("Shares") or row.get("shares") or 0),
                            "value": int(row.get("Value") or row.get("value") or 0),
                            "source": "yfinance",
                        })
                except Exception as e:
                    logger.debug("insider_transactions %s: %s", sym, e)
                return sym, trades[:6]

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_fetch_insider_yf, s): s for s in symbols}
                for fut in as_completed(futures):
                    sym, trades = fut.result()
                    insider_map[sym] = trades

        # --- Congressional trades (House + Senate STOCK Act) ---
        congress_by_symbol: dict[str, list] = {s: [] for s in symbol_set}
        sources = [
            "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
            "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
        ]
        headers = {"User-Agent": "schwab-ai-trader contact@example.com"}
        for url in sources:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    all_tx = json.loads(resp.read())
                for tx in all_tx:
                    ticker = (tx.get("ticker") or "").upper().strip()
                    if ticker not in symbol_set:
                        continue
                    raw_date = tx.get("transaction_date") or tx.get("date") or ""
                    try:
                        tx_date = datetime.strptime(raw_date[:10], "%Y-%m-%d")
                    except Exception:
                        continue
                    if tx_date < cutoff_dt:
                        continue
                    tx_type = (tx.get("type") or tx.get("transaction_type") or "").lower()
                    if tx_type not in ("purchase", "buy", "p"):
                        continue
                    congress_by_symbol[ticker].append({
                        "member": _sanitize(tx.get("representative") or tx.get("senator") or "", 80),
                        "party": _sanitize(tx.get("party") or "", 10),
                        "chamber": "house" if "house" in url else "senate",
                        "date": raw_date[:10],
                        "amount": _sanitize(tx.get("amount") or "", 30),
                    })
            except Exception as exc:
                logger.debug("Congressional trades fetch failed (%s): %s", url, exc)

        # --- Assemble result ---
        result: dict = {}
        for sym in symbols:
            sym_u = sym.upper()
            corp = insider_map.get(sym, [])
            cong = congress_by_symbol.get(sym_u, [])[:8]
            result[sym] = {
                "corporate_insider_buys": corp,
                "congressional_purchases": cong,
                "summary": (
                    f"{len(corp)} corporate insider buy(s), "
                    f"{len(cong)} congressional purchase(s) in last 90 days"
                ),
            }
        return json.dumps({"insider_activity": result})

    def get_earnings_revisions(self, symbols: list[str]) -> str:
        """EPS estimate changes over 30/90 days — rising revisions are a strong buy signal."""

        def _fetch(sym: str) -> tuple[str, dict]:
            try:
                t = yf.Ticker(sym)
                trend = t.eps_trend
                if trend is None or trend.empty:
                    return sym, {"error": "no EPS trend data"}
                out: dict = {}
                for period in trend.index:
                    row = trend.loc[period]
                    current = row.get("current")
                    ago30 = row.get("30daysAgo")
                    ago90 = row.get("90daysAgo")
                    rev30 = rev90 = None
                    if current is not None and ago30 and ago30 != 0:
                        rev30 = round((float(current) - float(ago30)) / abs(float(ago30)) * 100, 1)
                    if current is not None and ago90 and ago90 != 0:
                        rev90 = round((float(current) - float(ago90)) / abs(float(ago90)) * 100, 1)
                    direction = (
                        "raising" if (rev30 or 0) > 2
                        else "cutting" if (rev30 or 0) < -2
                        else "stable"
                    )
                    out[str(period)] = {
                        "eps_estimate": round(float(current), 4) if current is not None else None,
                        "revision_30d_pct": rev30,
                        "revision_90d_pct": rev90,
                        "direction": direction,
                    }
                return sym, out
            except Exception as exc:
                return sym, {"error": str(exc)}

        results: dict = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch, s): s for s in symbols}
            for fut in as_completed(futures):
                sym, data = fut.result()
                results[sym] = data
        return json.dumps({"earnings_revisions": results})

    def get_macro_context(self) -> str:
        """Market regime snapshot: VIX, SPY/QQQ vs 200MA, sector ETF momentum."""

        INDICES = ["SPY", "QQQ", "^VIX"]
        SECTORS = {
            "XLK": "Tech",
            "SMH": "Semiconductors",
            "XLF": "Financials",
            "XLE": "Energy",
            "XLV": "Healthcare",
            "XLY": "Consumer Discretionary",
            "XLI": "Industrials",
            "GLD": "Gold",
        }

        def _fetch_ticker(sym: str) -> tuple[str, dict]:
            try:
                hist = yf.Ticker(sym).history(period="1y")
                if hist.empty:
                    return sym, {"error": "no data"}
                closes = hist["Close"]
                current = float(closes.iloc[-1])
                ma200 = float(closes.rolling(min(200, len(closes))).mean().iloc[-1])
                ma50 = float(closes.rolling(min(50, len(closes))).mean().iloc[-1])
                chg_1m = float((closes.iloc[-1] / closes.iloc[-22] - 1) * 100) if len(closes) >= 22 else 0.0
                chg_3m = float((closes.iloc[-1] / closes.iloc[-63] - 1) * 100) if len(closes) >= 63 else 0.0
                return sym, {
                    "price": round(current, 2),
                    "ma_50": round(ma50, 2),
                    "ma_200": round(ma200, 2),
                    "above_200ma": current > ma200,
                    "above_50ma": current > ma50,
                    "chg_1m_pct": round(chg_1m, 1),
                    "chg_3m_pct": round(chg_3m, 1),
                }
            except Exception as exc:
                return sym, {"error": str(exc)}

        all_syms = INDICES + list(SECTORS.keys())
        data: dict = {}
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_ticker, s): s for s in all_syms}
            for fut in as_completed(futures):
                sym, d = fut.result()
                data[sym] = d

        # VIX regime signal
        vix = data.get("^VIX", {}).get("price", 20)
        if vix < 15:
            vix_regime = "low_fear (bullish)"
        elif vix < 20:
            vix_regime = "normal"
        elif vix < 30:
            vix_regime = "elevated_fear (cautious)"
        else:
            vix_regime = "high_fear (risk_off)"

        spy = data.get("SPY", {})
        qqq = data.get("QQQ", {})
        broad_bullish = spy.get("above_200ma") and qqq.get("above_200ma")
        regime = "BULLISH" if (broad_bullish and vix < 25) else "NEUTRAL" if broad_bullish else "BEARISH"

        sectors_out = {}
        for sym, label in SECTORS.items():
            d = data.get(sym, {})
            sectors_out[label] = {
                "symbol": sym,
                "chg_1m_pct": d.get("chg_1m_pct"),
                "chg_3m_pct": d.get("chg_3m_pct"),
                "above_200ma": d.get("above_200ma"),
            }

        # FRED macro indicators (non-blocking — skipped if no API key)
        fred_data: dict = {}
        try:
            from schwab_trader.core.settings import get_settings
            from schwab_trader.fred.service import get_macro_indicators
            _fred_key = get_settings().fred_api_key
            if _fred_key:
                fred_data = get_macro_indicators(_fred_key)
        except Exception as exc:
            logger.debug("FRED fetch skipped: %s", exc)

        return json.dumps({
            "regime": regime,
            "vix": vix,
            "vix_signal": vix_regime,
            "spy": {"price": spy.get("price"), "above_200ma": spy.get("above_200ma"), "chg_1m_pct": spy.get("chg_1m_pct"), "chg_3m_pct": spy.get("chg_3m_pct")},
            "qqq": {"price": qqq.get("price"), "above_200ma": qqq.get("above_200ma"), "chg_1m_pct": qqq.get("chg_1m_pct"), "chg_3m_pct": qqq.get("chg_3m_pct")},
            "sectors": sectors_out,
            "fred": fred_data,
            "interpretation": (
                f"Market regime: {regime}. VIX={vix:.1f} ({vix_regime}). "
                f"SPY {'above' if spy.get('above_200ma') else 'below'} 200MA, "
                f"QQQ {'above' if qqq.get('above_200ma') else 'below'} 200MA."
                + (f" {fred_data.get('interpretation', '')}" if fred_data else "")
            ),
        })


# ---------------------------------------------------------------------------
# Financial quality helpers
# ---------------------------------------------------------------------------

def _get_fin(df: Any, keys: list[str], col: int = 0) -> float | None:
    """Safely extract a numeric value from a yfinance financial DataFrame."""
    if df is None or not hasattr(df, "loc") or df.empty:
        return None
    for key in keys:
        try:
            if key not in df.index:
                continue
            row = df.loc[key]
            if len(row) <= col:
                continue
            v = row.iloc[col]
            if v is not None and not pd.isna(v):
                return float(v)
        except Exception:
            continue
    return None


def _piotroski_f_score(bs: Any, cf: Any, inc: Any) -> int | None:
    """Compute the 9-point Piotroski F-score. Returns None if data is insufficient.

    Profitability: F1 ROA>0, F2 CFO>0, F3 ΔROA>0, F4 accruals quality
    Leverage/liquidity: F5 Δleverage<0, F6 Δcurrent ratio>0, F7 no dilution proxy
    Operating efficiency: F8 Δgross margin>0, F9 Δasset turnover>0
    """
    if bs is None or cf is None or inc is None:
        return None

    ta0 = _get_fin(bs, ["Total Assets"], 0)
    ta1 = _get_fin(bs, ["Total Assets"], 1)
    ni0 = _get_fin(inc, ["Net Income", "Net Income Common Stockholders"], 0)
    ni1 = _get_fin(inc, ["Net Income", "Net Income Common Stockholders"], 1)
    cfo = _get_fin(cf, ["Operating Cash Flow", "Cash Flow From Operations"], 0)
    ca0 = _get_fin(bs, ["Current Assets", "Total Current Assets"], 0)
    cl0 = _get_fin(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
    ca1 = _get_fin(bs, ["Current Assets", "Total Current Assets"], 1)
    cl1 = _get_fin(bs, ["Current Liabilities", "Total Current Liabilities"], 1)
    tl0 = _get_fin(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 0)
    tl1 = _get_fin(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 1)
    gp0 = _get_fin(inc, ["Gross Profit"], 0)
    gp1 = _get_fin(inc, ["Gross Profit"], 1)
    rev0 = _get_fin(inc, ["Total Revenue"], 0)
    rev1 = _get_fin(inc, ["Total Revenue"], 1)
    re0 = _get_fin(bs, ["Retained Earnings"], 0)
    re1 = _get_fin(bs, ["Retained Earnings"], 1)

    score = 0

    # F1: ROA > 0
    roa0 = (ni0 / ta0) if (ni0 is not None and ta0 and ta0 > 0) else None
    if roa0 is not None and roa0 > 0:
        score += 1

    # F2: CFO > 0
    if cfo is not None and cfo > 0:
        score += 1

    # F3: ΔROA > 0
    roa1 = (ni1 / ta1) if (ni1 is not None and ta1 and ta1 > 0) else None
    if roa0 is not None and roa1 is not None and roa0 > roa1:
        score += 1

    # F4: Accruals — CFO/assets > ROA (cash earnings quality)
    if cfo is not None and ta0 and ta0 > 0 and roa0 is not None:
        if (cfo / ta0) > roa0:
            score += 1

    # F5: Leverage decreased (total liabilities / total assets)
    if tl0 is not None and ta0 and ta0 > 0 and tl1 is not None and ta1 and ta1 > 0:
        if (tl0 / ta0) < (tl1 / ta1):
            score += 1

    # F6: Current ratio improved
    cr0 = (ca0 / cl0) if (ca0 is not None and cl0 and cl0 > 0) else None
    cr1 = (ca1 / cl1) if (ca1 is not None and cl1 and cl1 > 0) else None
    if cr0 is not None and cr1 is not None and cr0 > cr1:
        score += 1

    # F7: No dilution — proxy: retained earnings grew (company is compounding)
    if re0 is not None and re1 is not None and re0 >= re1:
        score += 1

    # F8: Gross margin improved
    gm0 = (gp0 / rev0) if (gp0 is not None and rev0 and rev0 > 0) else None
    gm1 = (gp1 / rev1) if (gp1 is not None and rev1 and rev1 > 0) else None
    if gm0 is not None and gm1 is not None and gm0 > gm1:
        score += 1

    # F9: Asset turnover improved
    at0 = (rev0 / ta0) if (rev0 is not None and ta0 and ta0 > 0) else None
    at1 = (rev1 / ta1) if (rev1 is not None and ta1 and ta1 > 0) else None
    if at0 is not None and at1 is not None and at0 > at1:
        score += 1

    return score


def _altman_z_score(
    bs: Any, inc: Any, market_cap: float | None
) -> tuple[float | None, str | None]:
    """Compute Altman Z-score and distress zone.

    Z = 1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA) + 0.6*(MC/TL) + 1.0*(Rev/TA)
    Zones: safe >2.99 | grey 1.81–2.99 | distress <1.81
    Returns (None, None) if data is insufficient.
    """
    if bs is None or inc is None:
        return None, None

    ta = _get_fin(bs, ["Total Assets"], 0)
    if not ta or ta <= 0:
        return None, None

    ca = _get_fin(bs, ["Current Assets", "Total Current Assets"], 0) or 0.0
    cl = _get_fin(bs, ["Current Liabilities", "Total Current Liabilities"], 0) or 0.0
    re = _get_fin(bs, ["Retained Earnings"], 0) or 0.0
    tl = _get_fin(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 0) or 1.0
    rev = _get_fin(inc, ["Total Revenue"], 0) or 0.0
    ebit = _get_fin(inc, ["EBIT", "Operating Income", "Ebit"], 0) or 0.0
    mc = float(market_cap) if market_cap else 0.0

    wc = ca - cl
    z = (
        1.2 * (wc / ta)
        + 1.4 * (re / ta)
        + 3.3 * (ebit / ta)
        + 0.6 * (mc / tl)
        + 1.0 * (rev / ta)
    )

    if z > 2.99:
        zone = "safe"
    elif z > 1.81:
        zone = "grey"
    else:
        zone = "distress"

    return round(z, 2), zone
