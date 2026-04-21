from schwab_trader.risk.engine import check_order
from schwab_trader.risk.models import (
    AccountSnapshot,
    OrderIntent,
    OrderType,
    PositionSnapshot,
    RiskPolicy,
    TradeAction,
)


def test_check_order_allows_policy_compliant_entry() -> None:
    policy = RiskPolicy(
        allowed_symbols=["AAPL", "MSFT"],
        max_daily_loss_dollars=1_000,
        max_open_positions=5,
        max_order_notional_dollars=5_000,
        max_single_trade_risk_dollars=250,
        max_symbol_allocation_pct=0.25,
        require_stop_loss_for_entries=True,
    )
    account = AccountSnapshot(
        equity=20_000,
        cash=10_000,
        realized_pnl_today=-150,
        open_positions=[
            PositionSnapshot(symbol="MSFT", quantity=5, market_value=1_000, side=TradeAction.BUY)
        ],
    )
    order = OrderIntent(
        symbol="AAPL",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=20,
        reference_price=150,
        limit_price=149,
        stop_price=142,
    )

    result = check_order(order=order, policy=policy, account=account)

    assert result.allowed is True
    assert result.reasons == []
    assert round(result.requested_notional, 2) == 2_980.0
    assert round(result.estimated_trade_risk, 2) == 140.0


def test_check_order_blocks_orders_when_limits_are_breached() -> None:
    policy = RiskPolicy(
        allowed_symbols=["AAPL"],
        max_daily_loss_dollars=500,
        max_open_positions=1,
        max_order_notional_dollars=2_000,
        max_single_trade_risk_dollars=100,
        max_symbol_allocation_pct=0.10,
        require_stop_loss_for_entries=True,
    )
    account = AccountSnapshot(
        equity=10_000,
        cash=1_000,
        realized_pnl_today=-600,
        open_positions=[
            PositionSnapshot(symbol="MSFT", quantity=10, market_value=2_000, side=TradeAction.BUY)
        ],
    )
    order = OrderIntent(
        symbol="TSLA",
        action=TradeAction.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        reference_price=300,
    )

    result = check_order(order=order, policy=policy, account=account)

    assert result.allowed is False
    assert "Symbol TSLA is not approved by the current risk policy." in result.reasons
    assert "Daily loss limit has already been breached." in result.reasons
    assert "Maximum open positions would be exceeded by this order." in result.reasons
    assert "A stop price is required for new entries under the current policy." in result.reasons
    assert "Order notional exceeds the configured cap." in result.reasons
