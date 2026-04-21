"""Portfolio performance service — snapshots + metrics."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import yfinance as yf

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.performance.store import PerformanceStore

logger = logging.getLogger(__name__)

# Annualised risk-free rate (approximate 10-yr treasury)
_RISK_FREE_ANNUAL = 0.045
_RISK_FREE_DAILY = _RISK_FREE_ANNUAL / 252


def _std(values: list[float]) -> float:
    """Population std-dev (pure Python, no numpy needed)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def _cov(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (n - 1)


class PerformanceService:
    """Take snapshots and compute performance metrics."""

    def __init__(self, store: PerformanceStore) -> None:
        self._store = store

    # ── snapshot ──────────────────────────────────────────────────────────────

    def take_snapshot(self, broker_service: SchwabBrokerService) -> dict | None:
        """Capture today's portfolio value + benchmark closes.

        Safe to call multiple times per day — upserts by date.
        Returns the snapshot dict, or None on failure.
        """
        try:
            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                logger.warning("Performance snapshot skipped: no accounts")
                return None

            acct = accounts[0].get("securitiesAccount", {})
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            portfolio_value = float(bal.get("liquidationValue") or 0)
            cash_value = float(bal.get("cashBalance") or bal.get("cashEquivalents") or 0)

            if portfolio_value <= 0:
                logger.warning("Performance snapshot skipped: portfolio_value=%s", portfolio_value)
                return None

            # Benchmark prices from Schwab quotes (avoid yfinance latency in hot path)
            spy_close: float | None = None
            qqq_close: float | None = None
            try:
                quotes = broker_service.get_quotes(["SPY", "QQQ"])
                spy_close = quotes.get("SPY", {}).get("quote", {}).get("closePrice")
                qqq_close = quotes.get("QQQ", {}).get("quote", {}).get("closePrice")
            except Exception:
                logger.debug("Benchmark quotes unavailable, skipping", exc_info=True)

            # Build light positions snapshot (symbol + market value only)
            raw_positions = acct.get("positions", [])
            positions = [
                {
                    "symbol": p["instrument"]["symbol"],
                    "qty": (p.get("longQuantity") or 0) - (p.get("shortQuantity") or 0),
                    "market_value": p.get("marketValue") or 0,
                }
                for p in raw_positions
                if p.get("instrument")
            ]

            today = date.today().isoformat()
            now = datetime.now(timezone.utc).isoformat()

            snapshot = {
                "date": today,
                "timestamp": now,
                "portfolio_value": portfolio_value,
                "cash_value": cash_value,
                "spy_close": spy_close,
                "qqq_close": qqq_close,
                "positions": positions,
            }
            self._store.upsert(**snapshot)
            logger.info(
                "Performance snapshot saved: $%,.2f on %s (SPY=%.2f)",
                portfolio_value,
                today,
                spy_close or 0,
            )
            return snapshot

        except Exception:
            logger.exception("Performance snapshot failed")
            return None

    # ── history ───────────────────────────────────────────────────────────────

    def get_history(self, days: int = 90) -> dict:
        """Return snapshot series + computed metrics + benchmark for charting.

        If there are fewer than 2 snapshots the metrics will be minimal but
        the response is still valid (frontend shows a "collecting" state).
        """
        since = (date.today() - timedelta(days=days)).isoformat()
        snapshots = self._store.get_since(since)
        total_count = self._store.count()

        if len(snapshots) < 2:
            # Return whatever we have so the UI can show a sensible placeholder
            return {
                "snapshots": snapshots,
                "metrics": {},
                "benchmark": [],
                "total_snapshots": total_count,
                "collecting": True,
            }

        # ── compute returns ─────────────────────────────────────────────
        values = [s["portfolio_value"] for s in snapshots]
        dates = [s["date"] for s in snapshots]

        daily_returns = [
            (values[i] - values[i - 1]) / values[i - 1]
            for i in range(1, len(values))
        ]

        total_return_pct = (values[-1] / values[0] - 1) * 100

        n_days = (
            datetime.strptime(dates[-1], "%Y-%m-%d")
            - datetime.strptime(dates[0], "%Y-%m-%d")
        ).days or 1
        annual_return_pct = ((1 + total_return_pct / 100) ** (365 / n_days) - 1) * 100

        vol = _std(daily_returns) * math.sqrt(252) * 100  # annualised %
        mean_dr = sum(daily_returns) / len(daily_returns)
        sharpe = (
            (mean_dr - _RISK_FREE_DAILY) / (_std(daily_returns) or 1e-9)
        ) * math.sqrt(252)

        # Max drawdown
        peak, max_dd = values[0], 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
        max_dd_pct = max_dd * 100

        best_day_pct = max(daily_returns) * 100 if daily_returns else 0
        worst_day_pct = min(daily_returns) * 100 if daily_returns else 0
        win_days = sum(1 for r in daily_returns if r > 0)
        win_rate = win_days / len(daily_returns) * 100 if daily_returns else 0

        # ── benchmark series ────────────────────────────────────────────
        benchmark = self._fetch_benchmark(snapshots)

        # ── benchmark metrics ───────────────────────────────────────────
        spy_return_pct: float | None = None
        beta: float | None = None
        if benchmark:
            bm_values = [b["spy_close"] for b in benchmark if b.get("spy_close")]
            if len(bm_values) >= 2:
                spy_return_pct = (bm_values[-1] / bm_values[0] - 1) * 100

            # Align dates for beta calculation
            bm_by_date = {b["date"]: b.get("spy_close") for b in benchmark}
            paired = [
                (daily_returns[i], (bm_by_date.get(dates[i + 1], 0) or 0) /
                 (bm_by_date.get(dates[i], 0) or 1) - 1)
                for i in range(len(daily_returns))
                if bm_by_date.get(dates[i + 1]) and bm_by_date.get(dates[i])
            ]
            if len(paired) >= 5:
                port_r = [p[0] for p in paired]
                spy_r = [p[1] for p in paired]
                var_spy = _std(spy_r) ** 2
                beta = _cov(port_r, spy_r) / (var_spy or 1e-9)

        metrics = {
            "total_return_pct": round(total_return_pct, 2),
            "annual_return_pct": round(annual_return_pct, 2),
            "sharpe": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "volatility_pct": round(vol, 2),
            "best_day_pct": round(best_day_pct, 2),
            "worst_day_pct": round(worst_day_pct, 2),
            "win_rate_pct": round(win_rate, 1),
            "spy_return_pct": round(spy_return_pct, 2) if spy_return_pct is not None else None,
            "beta": round(beta, 2) if beta is not None else None,
            "days_tracked": len(snapshots),
            "start_value": values[0],
            "current_value": values[-1],
        }

        return {
            "snapshots": snapshots,
            "metrics": metrics,
            "benchmark": benchmark,
            "total_snapshots": total_count,
            "collecting": False,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def backfill(self, broker_service: SchwabBrokerService, days: int = 90) -> int:
        """Estimate historical portfolio values using current holdings × historical closes.

        Skips dates that already have a real snapshot.  Returns number of dates inserted.
        Clearly marked as estimated — values assume no trades were made in the period.
        """
        try:
            # Current positions
            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                return 0
            acct = accounts[0].get("securitiesAccount", {})
            raw_pos = acct.get("positions", [])
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            cash = float(bal.get("cashBalance") or bal.get("cashEquivalents") or 0)

            holdings: list[tuple[str, float]] = []
            for p in raw_pos:
                sym = p.get("instrument", {}).get("symbol")
                qty = (p.get("longQuantity") or 0) - (p.get("shortQuantity") or 0)
                if sym and qty:
                    holdings.append((sym, float(qty)))

            if not holdings:
                return 0

            symbols = [h[0] for h in holdings] + ["SPY", "QQQ"]
            start = (date.today() - timedelta(days=days + 5)).isoformat()
            end   = (date.today() + timedelta(days=1)).isoformat()

            logger.info("Backfilling %d days with %d symbols…", days, len(holdings))
            raw = yf.download(
                symbols, start=start, end=end,
                progress=False, auto_adjust=True, group_by="ticker",
            )

            # Build {date_str: {symbol: close}}
            closes_by_date: dict[str, dict[str, float]] = {}
            for col in raw.columns:
                if col[1] != "Close":
                    continue
                sym = col[0]
                for idx, val in raw[col].items():
                    if hasattr(val, "item"):
                        val = val.item()
                    if val and not (isinstance(val, float) and (val != val)):  # skip NaN
                        d_str = idx.strftime("%Y-%m-%d")
                        closes_by_date.setdefault(d_str, {})[sym] = float(val)

            # Existing dates — skip (don't overwrite real snapshots)
            existing = {s["date"] for s in self._store.get_since(
                (date.today() - timedelta(days=days + 5)).isoformat()
            )}

            inserted = 0
            for d_str in sorted(closes_by_date.keys()):
                if d_str in existing:
                    continue
                closes = closes_by_date[d_str]
                # Require all holdings to have prices for this date
                missing = [s for s, _ in holdings if s not in closes]
                if missing:
                    continue
                port_val = sum(qty * closes[sym] for sym, qty in holdings) + cash
                self._store.upsert(
                    date=d_str,
                    timestamp=f"{d_str}T21:00:00+00:00",  # approximate close time
                    portfolio_value=round(port_val, 2),
                    cash_value=round(cash, 2),
                    spy_close=closes.get("SPY"),
                    qqq_close=closes.get("QQQ"),
                    positions=[{"symbol": s, "qty": q, "market_value": round(q * closes[s], 2)}
                                for s, q in holdings],
                )
                inserted += 1

            if inserted:
                logger.info("Backfilled %d estimated snapshots", inserted)
            return inserted

        except Exception:
            logger.exception("Backfill failed")
            return 0

    def rebuild_full_history(
        self, broker_service: SchwabBrokerService, years: int = 10
    ) -> dict:
        """Reconstruct ALL-TIME portfolio history from actual Schwab transactions.

        Algorithm
        ---------
        1. Fetch every TRADE transaction Schwab has (1-year windows going back ``years`` years).
        2. Starting from today's holdings, walk *backward* through those transactions to
           reconstruct what you actually owned on each historical date:
              BUY  → going back, un-buy those shares (portfolio was smaller)
              SELL → going back, re-add those shares (portfolio was larger)
        3. Fill every calendar date between the oldest known state and today.
        4. Price each day's holdings with yfinance and upsert into the performance DB.
        5. Falls back to the simple current-holdings backfill when no transaction data
           is available.

        Returns a dict with ``inserted``, ``dates_covered``, and ``method`` keys.
        """
        try:
            # ── 1. Fetch transaction history ──────────────────────────────────
            account_hash = broker_service.get_primary_account_hash()
            today = date.today()
            all_txns: list[dict] = []

            for yr in range(years):
                win_end   = today - timedelta(days=yr * 365)
                win_start = win_end - timedelta(days=364)
                try:
                    chunk = broker_service.get_transactions(
                        account_hash=account_hash,
                        start_date=win_start.strftime("%Y-%m-%dT00:00:00Z"),
                        end_date=win_end.strftime("%Y-%m-%dT23:59:59Z"),
                        types=["TRADE"],
                    )
                    if chunk:
                        all_txns.extend(chunk)
                        logger.info(
                            "Fetched %d transactions for window %s – %s",
                            len(chunk), win_start, win_end,
                        )
                    else:
                        # No data this far back — stop extending
                        break
                except Exception:
                    logger.debug("Transaction fetch failed for window %s – %s", win_start, win_end, exc_info=True)
                    break

            # Deduplicate
            seen_ids: set = set()
            unique_txns: list[dict] = []
            for t in all_txns:
                tid = t.get("activityId") or id(t)
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    unique_txns.append(t)

            # Sort oldest → newest
            unique_txns.sort(key=lambda t: (t.get("tradeDate") or t.get("time") or ""))

            # ── 2. Get current holdings ───────────────────────────────────────
            accounts = broker_service.get_accounts(fields=["positions"])
            if not accounts:
                return {"inserted": 0, "dates_covered": 0, "method": "no_accounts"}
            acct = accounts[0].get("securitiesAccount", {})
            raw_pos = acct.get("positions", [])
            bal = acct.get("currentBalances") or acct.get("initialBalances") or {}
            cash = float(bal.get("cashBalance") or bal.get("cashEquivalents") or 0)

            current_holdings: dict[str, float] = {}
            for p in raw_pos:
                sym = p.get("instrument", {}).get("symbol", "")
                qty = (p.get("longQuantity") or 0) - (p.get("shortQuantity") or 0)
                if sym and qty:
                    current_holdings[sym] = float(qty)

            # ── 3. Fall back if no transactions at all ────────────────────────
            if not unique_txns:
                logger.info("No transaction data — using extended holdings-based backfill (%d yr)", years)
                n = self.backfill(broker_service, days=years * 365)
                return {"inserted": n, "dates_covered": n, "method": "holdings_estimate"}

            # ── 4. Backward reconstruction ────────────────────────────────────
            # holdings_timeline: date_str → {sym: qty}  (snapshot at start of that day)
            holdings_timeline: dict[str, dict[str, float]] = {}
            holdings_timeline[today.isoformat()] = dict(current_holdings)

            # Walk newest → oldest, un-applying each trade
            state = dict(current_holdings)
            for txn in reversed(unique_txns):
                txn_date = (txn.get("tradeDate") or txn.get("time") or "")[:10]
                if not txn_date:
                    continue
                item = txn.get("transactionItem") or {}
                inst = item.get("instrument") or {}
                sym = inst.get("symbol", "")
                asset = inst.get("assetType", "")
                if not sym or asset == "OPTION":
                    continue

                qty = float(item.get("quantity") or 0)
                instruction = (item.get("instruction") or "").upper()

                if instruction == "BUY":
                    # Un-buy: remove these shares from pre-purchase state
                    state[sym] = state.get(sym, 0) - qty
                    if state[sym] < 0.001:
                        state.pop(sym, None)
                elif instruction == "SELL":
                    # Un-sell: add these shares back to pre-sale state
                    state[sym] = state.get(sym, 0) + qty

                holdings_timeline[txn_date] = {k: v for k, v in state.items() if v > 0.001}

            # ── 5. Fill every calendar date ───────────────────────────────────
            timeline_dates = sorted(holdings_timeline.keys())
            oldest_date    = date.fromisoformat(timeline_dates[0])

            # Build {date_str → holdings} for every day from oldest to today
            date_to_state: dict[str, dict[str, float]] = {}
            cursor = oldest_date
            state_idx = 0
            while cursor <= today:
                d_str = cursor.isoformat()
                # Find the most-recent snapshot at or before cursor
                applicable: dict[str, float] = {}
                for td in timeline_dates:
                    if td <= d_str:
                        applicable = holdings_timeline[td]
                    else:
                        break
                date_to_state[d_str] = applicable
                cursor += timedelta(days=1)

            # ── 6. Collect symbols and fetch yfinance history ─────────────────
            all_syms: set[str] = {"SPY", "QQQ"}
            for s in date_to_state.values():
                all_syms.update(s.keys())

            yf_start = (oldest_date - timedelta(days=5)).isoformat()
            yf_end   = (today + timedelta(days=1)).isoformat()

            logger.info("Fetching yfinance data for %d symbols from %s", len(all_syms), yf_start)
            raw = yf.download(
                list(all_syms), start=yf_start, end=yf_end,
                progress=False, auto_adjust=True, group_by="ticker",
            )

            closes_by_date: dict[str, dict[str, float]] = {}
            for col in raw.columns:
                if col[1] != "Close":
                    continue
                sym = col[0]
                for idx, val in raw[col].items():
                    if hasattr(val, "item"):
                        val = val.item()
                    if val and not (isinstance(val, float) and val != val):
                        closes_by_date.setdefault(idx.strftime("%Y-%m-%d"), {})[sym] = float(val)

            # ── 7. Upsert snapshots (skip existing real snapshots) ────────────
            existing = {
                s["date"] for s in self._store.get_since(
                    (oldest_date - timedelta(days=5)).isoformat()
                )
            }

            inserted = 0
            for d_str in sorted(closes_by_date.keys()):
                if d_str in existing:
                    continue
                h = date_to_state.get(d_str, {})
                if not h:
                    continue
                closes = closes_by_date[d_str]
                # Skip dates where we can't price >50% of holdings by value
                priced_qty = sum(q for s, q in h.items() if closes.get(s))
                total_qty  = sum(h.values()) or 1
                if priced_qty / total_qty < 0.5:
                    continue

                port_val = sum(q * closes[s] for s, q in h.items() if closes.get(s)) + cash
                if port_val <= 0:
                    continue

                self._store.upsert(
                    date=d_str,
                    timestamp=f"{d_str}T21:00:00+00:00",
                    portfolio_value=round(port_val, 2),
                    cash_value=round(cash, 2),
                    spy_close=closes.get("SPY"),
                    qqq_close=closes.get("QQQ"),
                    positions=[
                        {"symbol": s, "qty": q, "market_value": round(q * closes[s], 2)}
                        for s, q in h.items() if closes.get(s)
                    ],
                )
                inserted += 1

            if inserted:
                logger.info("Rebuilt %d all-time snapshots using transaction data", inserted)

            return {
                "inserted": inserted,
                "dates_covered": len(date_to_state),
                "method": "transaction_reconstruction",
                "transactions_used": len(unique_txns),
                "oldest_date": oldest_date.isoformat(),
            }

        except Exception:
            logger.exception("rebuild_full_history failed")
            return {"inserted": 0, "dates_covered": 0, "method": "error"}

    def _fetch_benchmark(self, snapshots: list[dict]) -> list[dict]:
        """Return SPY closes aligned to snapshot dates.

        Uses closes already stored in DB when available; fills gaps with yfinance.
        """
        if not snapshots:
            return []

        # Use stored closes first
        stored: dict[str, float | None] = {
            s["date"]: s.get("spy_close") for s in snapshots
        }

        missing_dates = [d for d, v in stored.items() if v is None]

        if missing_dates:
            try:
                start = min(missing_dates)
                end = (
                    datetime.strptime(max(missing_dates), "%Y-%m-%d") + timedelta(days=2)
                ).strftime("%Y-%m-%d")
                spy = yf.download("SPY", start=start, end=end, progress=False, auto_adjust=True)
                for idx, row in spy.iterrows():
                    d_str = idx.strftime("%Y-%m-%d")
                    if d_str in stored:
                        close_val = row.get("Close")
                        if hasattr(close_val, "item"):
                            close_val = close_val.item()
                        stored[d_str] = float(close_val) if close_val else None
            except Exception:
                logger.debug("yfinance benchmark fetch failed", exc_info=True)

        return [
            {"date": d, "spy_close": v}
            for d, v in sorted(stored.items())
            if v is not None
        ]
