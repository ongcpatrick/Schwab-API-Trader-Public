"""Trade evaluation metrics."""

from collections import defaultdict
from collections.abc import Sequence

from schwab_trader.journal.models import (
    CompletedTrade,
    SymbolScorecard,
    TradeEvaluationSummary,
    TradeScorecard,
    TradeSide,
)


def _gross_pnl(trade: CompletedTrade) -> float:
    if trade.side is TradeSide.LONG:
        return (trade.exit_price - trade.entry_price) * trade.quantity
    return (trade.entry_price - trade.exit_price) * trade.quantity


def _net_pnl(trade: CompletedTrade) -> float:
    return _gross_pnl(trade) - trade.fees


def _return_pct(trade: CompletedTrade) -> float:
    if trade.side is TradeSide.LONG:
        return ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
    return ((trade.entry_price - trade.exit_price) / trade.entry_price) * 100


def evaluate_completed_trades(trades: Sequence[CompletedTrade]) -> TradeEvaluationSummary:
    """Compute evaluation metrics for completed trades."""

    if not trades:
        return TradeEvaluationSummary(
            total_trades=0,
            gross_pnl=0,
            net_pnl=0,
            win_rate=0,
            avg_win=0,
            avg_loss=0,
            profit_factor=0,
            expectancy=0,
            average_holding_minutes=0,
            benchmark_outperformance_rate=0,
            plan_adherence_rate=0,
            max_consecutive_losses=0,
            warnings=["No completed trades were provided."],
        )

    net_results = [_net_pnl(trade) for trade in trades]
    gross_results = [_gross_pnl(trade) for trade in trades]
    winning_trades = [result for result in net_results if result > 0]
    losing_trades = [result for result in net_results if result < 0]

    total_trades = len(trades)
    win_rate = len(winning_trades) / total_trades
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0
    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss else 0
    expectancy = sum(net_results) / total_trades

    hold_minutes = [trade.hold_minutes for trade in trades if trade.hold_minutes is not None]
    average_holding_minutes = sum(hold_minutes) / len(hold_minutes) if hold_minutes else 0

    benchmark_checks = [
        _return_pct(trade) > trade.benchmark_return_pct
        for trade in trades
        if trade.benchmark_return_pct is not None
    ]
    benchmark_outperformance_rate = (
        sum(1 for passed in benchmark_checks if passed) / len(benchmark_checks)
        if benchmark_checks
        else 0
    )

    plan_flags = [trade.followed_plan for trade in trades if trade.followed_plan is not None]
    plan_adherence_rate = (
        sum(1 for followed in plan_flags if followed) / len(plan_flags) if plan_flags else 0
    )

    max_consecutive_losses = 0
    current_loss_streak = 0
    for result in net_results:
        if result < 0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0

    return TradeEvaluationSummary(
        total_trades=total_trades,
        gross_pnl=sum(gross_results),
        net_pnl=sum(net_results),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        average_holding_minutes=average_holding_minutes,
        benchmark_outperformance_rate=benchmark_outperformance_rate,
        plan_adherence_rate=plan_adherence_rate,
        max_consecutive_losses=max_consecutive_losses,
    )


def build_trade_scorecard(
    trades: Sequence[CompletedTrade],
    *,
    warnings: Sequence[str] = (),
) -> TradeScorecard:
    """Build a top-level scorecard plus grouped symbol statistics."""

    summary = evaluate_completed_trades(trades)
    grouped: dict[str, list[CompletedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)

    symbol_stats = [
        SymbolScorecard(
            symbol=symbol,
            **evaluate_completed_trades(symbol_trades).model_dump(
                include={
                    "total_trades",
                    "gross_pnl",
                    "net_pnl",
                    "win_rate",
                    "avg_win",
                    "avg_loss",
                    "profit_factor",
                    "expectancy",
                    "average_holding_minutes",
                    "benchmark_outperformance_rate",
                    "max_consecutive_losses",
                }
            ),
        )
        for symbol, symbol_trades in sorted(grouped.items())
    ]
    return TradeScorecard(summary=summary, symbol_stats=symbol_stats, warnings=list(warnings))
