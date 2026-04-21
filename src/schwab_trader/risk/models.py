"""Risk domain models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TradeAction(StrEnum):
    """Order or position direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Supported order types for pre-trade checks."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class PositionSnapshot(BaseModel):
    """Current account position exposure."""

    symbol: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    market_value: float = Field(ge=0)
    side: TradeAction


class AccountSnapshot(BaseModel):
    """Account state used for risk checks."""

    equity: float = Field(gt=0)
    cash: float = Field(ge=0)
    realized_pnl_today: float = 0
    open_positions: list[PositionSnapshot] = Field(default_factory=list)


class RiskPolicy(BaseModel):
    """Top-level risk guardrails."""

    allowed_symbols: list[str] | None = None
    max_daily_loss_dollars: float | None = Field(default=None, gt=0)
    max_open_positions: int | None = Field(default=None, gt=0)
    max_order_notional_dollars: float | None = Field(default=None, gt=0)
    max_single_trade_risk_dollars: float | None = Field(default=None, gt=0)
    max_symbol_allocation_pct: float | None = Field(default=None, gt=0, le=1)
    require_stop_loss_for_entries: bool = False


class OrderIntent(BaseModel):
    """Order request before broker preview or submission."""

    symbol: str = Field(min_length=1)
    action: TradeAction
    order_type: OrderType
    quantity: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)

    def working_price(self) -> float:
        """Return the price to use for notional checks."""

        return self.limit_price or self.reference_price


class RiskCheckResult(BaseModel):
    """Outcome of the risk engine preflight."""

    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requested_notional: float
    estimated_trade_risk: float | None = None
