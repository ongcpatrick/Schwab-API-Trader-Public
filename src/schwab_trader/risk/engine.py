"""Pre-trade risk engine."""

from schwab_trader.risk.models import (
    AccountSnapshot,
    OrderIntent,
    RiskCheckResult,
    RiskPolicy,
    TradeAction,
)


def check_order(
    order: OrderIntent,
    policy: RiskPolicy,
    account: AccountSnapshot,
) -> RiskCheckResult:
    """Evaluate whether an order passes the current risk policy."""

    reasons: list[str] = []
    warnings: list[str] = []

    working_price = order.working_price()
    requested_notional = working_price * order.quantity
    estimated_trade_risk = (
        abs(working_price - order.stop_price) * order.quantity if order.stop_price else None
    )

    existing_symbols = {position.symbol.upper() for position in account.open_positions}
    normalized_symbol = order.symbol.upper()

    if policy.allowed_symbols:
        approved_symbols = {symbol.upper() for symbol in policy.allowed_symbols}
        if normalized_symbol not in approved_symbols:
            reasons.append(
                f"Symbol {normalized_symbol} is not approved by the current risk policy."
            )

    if (
        policy.max_daily_loss_dollars is not None
        and account.realized_pnl_today <= -policy.max_daily_loss_dollars
    ):
        reasons.append("Daily loss limit has already been breached.")

    if (
        policy.max_open_positions is not None
        and normalized_symbol not in existing_symbols
        and len(account.open_positions) >= policy.max_open_positions
    ):
        reasons.append("Maximum open positions would be exceeded by this order.")

    if (
        policy.require_stop_loss_for_entries
        and order.action is TradeAction.BUY
        and not order.stop_price
    ):
        reasons.append("A stop price is required for new entries under the current policy.")

    if (
        policy.max_order_notional_dollars is not None
        and requested_notional > policy.max_order_notional_dollars
    ):
        reasons.append("Order notional exceeds the configured cap.")

    if order.action is TradeAction.BUY and requested_notional > account.cash:
        reasons.append("Insufficient available cash for this order.")

    if (
        policy.max_single_trade_risk_dollars is not None
        and estimated_trade_risk is not None
        and estimated_trade_risk > policy.max_single_trade_risk_dollars
    ):
        reasons.append("Estimated trade risk exceeds the configured cap.")

    if estimated_trade_risk is None and order.action is TradeAction.BUY:
        warnings.append("Unable to estimate trade risk without a stop price.")

    if policy.max_symbol_allocation_pct is not None:
        current_symbol_value = sum(
            position.market_value
            for position in account.open_positions
            if position.symbol.upper() == normalized_symbol
        )
        projected_symbol_value = current_symbol_value
        if order.action is TradeAction.BUY:
            projected_symbol_value += requested_notional
        else:
            projected_symbol_value = max(current_symbol_value - requested_notional, 0)

        projected_allocation = projected_symbol_value / account.equity
        if projected_allocation > policy.max_symbol_allocation_pct:
            reasons.append("Projected symbol allocation exceeds the configured cap.")

    return RiskCheckResult(
        allowed=not reasons,
        reasons=reasons,
        warnings=warnings,
        requested_notional=requested_notional,
        estimated_trade_risk=estimated_trade_risk,
    )
