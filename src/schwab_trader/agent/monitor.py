"""Portfolio flag detection — scans positions and returns actionable signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Flag:
    type: str
    symbol: str
    severity: str  # HIGH | MEDIUM | LOW
    description: str
    proposed_action: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "symbol": self.symbol,
            "severity": self.severity,
            "description": self.description,
            "proposed_action": self.proposed_action,
        }


def check_portfolio(
    positions: list[dict],
    calendar: list[dict],
    portfolio_value: float,
    *,
    earnings_days_threshold: int = 3,
    position_down_pct: float = 8.0,
    day_loss_pct: float = 5.0,
    concentration_pct: float = 25.0,
    gain_alert_pct: float = 30.0,
    muted_symbols: set[str] | None = None,
) -> list[Flag]:
    """Scan positions and return a list of actionable flags."""
    muted = muted_symbols or set()
    flags: list[Flag] = []
    cal_map = {e["symbol"]: e for e in calendar}

    for p in positions:
        sym = p["symbol"]
        if sym in muted:
            continue
        qty = p["qty"]
        avg = p["avg_cost"]
        mkt = p["market_value"]
        cost = p["cost_basis"]
        day_pct = p["day_pct"]
        total_pct = (mkt - cost) / cost * 100 if cost else 0
        weight = mkt / portfolio_value * 100 if portfolio_value else 0

        # Earnings imminent
        cal = cal_map.get(sym)
        if cal and 0 <= cal["days_until"] <= earnings_days_threshold:
            d = cal["days_until"]
            when = "TODAY" if d == 0 else "TOMORROW" if d == 1 else f"in {d} days"
            flags.append(Flag(
                type="EARNINGS_IMMINENT",
                symbol=sym,
                severity="HIGH" if d <= 1 else "MEDIUM",
                description=f"{sym} reports earnings {when} ({cal['date']})",
                proposed_action=(
                    f"Review: {qty:.4f} shares @ avg ${avg:.2f}. "
                    "Decide hold, trim, or hedge before the report."
                ),
            ))

        # Position down significantly from cost basis
        if cost > 0 and total_pct <= -position_down_pct:
            cur_price = mkt / abs(qty) if qty else 0
            flags.append(Flag(
                type="POSITION_DOWN",
                symbol=sym,
                severity="HIGH",
                description=f"{sym} down {total_pct:.1f}% from avg cost (${avg:.2f} → ${cur_price:.2f})",
                proposed_action="Evaluate stop-loss, averaging down, or cutting losses.",
            ))

        # Large single-day loss
        if day_pct <= -day_loss_pct:
            flags.append(Flag(
                type="DAY_LOSS",
                symbol=sym,
                severity="MEDIUM",
                description=f"{sym} down {day_pct:.1f}% today",
                proposed_action="Check for news catalyst. Monitor for continued weakness.",
            ))

        # Concentration risk
        if portfolio_value > 0 and weight >= concentration_pct:
            flags.append(Flag(
                type="CONCENTRATION",
                symbol=sym,
                severity="MEDIUM",
                description=f"{sym} is {weight:.1f}% of portfolio (threshold: {concentration_pct:.0f}%)",
                proposed_action=f"Consider trimming to reduce concentration. Target weight: <{concentration_pct:.0f}%.",
            ))

        # Large unrealized gain — profit-taking opportunity
        if total_pct >= gain_alert_pct:
            flags.append(Flag(
                type="LARGE_GAIN",
                symbol=sym,
                severity="LOW",
                description=f"{sym} up {total_pct:.1f}% — strong unrealized gain",
                proposed_action="Consider partial profit-taking or a trailing stop to protect gains.",
            ))

    return flags
