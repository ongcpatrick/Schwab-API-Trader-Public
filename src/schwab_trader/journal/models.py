"""Trade journal domain models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TradeSide(StrEnum):
    """Supported trade directions for completed trades."""

    LONG = "long"
    SHORT = "short"


class CompletedTrade(BaseModel):
    """A normalized completed trade used for journal analytics."""

    symbol: str = Field(min_length=1)
    side: TradeSide
    quantity: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    fees: float = Field(default=0, ge=0)
    benchmark_return_pct: float | None = None
    followed_plan: bool | None = None
    hold_minutes: int | None = Field(default=None, ge=0)


class TradeEvaluationSummary(BaseModel):
    """Aggregate metrics over a set of completed trades."""

    total_trades: int
    gross_pnl: float
    net_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    average_holding_minutes: float
    benchmark_outperformance_rate: float
    plan_adherence_rate: float
    max_consecutive_losses: int
    warnings: list[str] = Field(default_factory=list)


class SyncRunStatus(StrEnum):
    """Supported sync-run states."""

    SUCCESS = "success"
    FAILED = "failed"


class SyncRunSummary(BaseModel):
    """Summary of a local Schwab sync run."""

    run_id: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    status: SyncRunStatus
    orders_from: datetime
    orders_to: datetime
    transactions_from: datetime
    transactions_to: datetime
    accounts_synced: int = Field(ge=0)
    orders_synced: int = Field(ge=0)
    transactions_synced: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None


class JournalOverview(BaseModel):
    """High-level local journal counts and latest sync metadata."""

    account_count: int = Field(ge=0)
    order_count: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    last_sync: SyncRunSummary | None = None


class StoredCompletedTrade(CompletedTrade):
    """A reconstructed completed trade persisted in the local journal."""

    trade_id: str = Field(min_length=1)
    account_hash: str = Field(min_length=1)
    gross_pnl: float
    net_pnl: float
    entry_time: datetime
    exit_time: datetime
    entry_order_id: str | None = None
    exit_order_id: str | None = None
    entry_transaction_id: str | None = None
    exit_transaction_id: str | None = None


class SymbolScorecard(BaseModel):
    """Per-symbol performance summary over reconstructed completed trades."""

    symbol: str
    total_trades: int
    gross_pnl: float
    net_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    average_holding_minutes: float
    benchmark_outperformance_rate: float
    max_consecutive_losses: int


class TradeScorecard(BaseModel):
    """High-level scorecard for reconstructed completed trades."""

    summary: TradeEvaluationSummary
    symbol_stats: list[SymbolScorecard] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompletedTradeRebuildSummary(BaseModel):
    """Summary of a completed-trade reconstruction run."""

    completed_trade_count: int = Field(ge=0)
    open_lot_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
