from schwab_trader.journal.metrics import evaluate_completed_trades
from schwab_trader.journal.models import CompletedTrade, TradeSide


def test_evaluate_completed_trades_calculates_key_metrics() -> None:
    trades = [
        CompletedTrade(
            symbol="AAPL",
            side=TradeSide.LONG,
            quantity=10,
            entry_price=100,
            exit_price=110,
            fees=1,
            benchmark_return_pct=2.0,
            followed_plan=True,
            hold_minutes=60,
        ),
        CompletedTrade(
            symbol="MSFT",
            side=TradeSide.LONG,
            quantity=5,
            entry_price=200,
            exit_price=190,
            fees=1,
            benchmark_return_pct=-1.0,
            followed_plan=False,
            hold_minutes=30,
        ),
        CompletedTrade(
            symbol="NVDA",
            side=TradeSide.SHORT,
            quantity=2,
            entry_price=140,
            exit_price=130,
            fees=0,
            benchmark_return_pct=1.0,
            followed_plan=True,
            hold_minutes=90,
        ),
    ]

    summary = evaluate_completed_trades(trades)

    assert summary.total_trades == 3
    assert round(summary.gross_pnl, 2) == 70.0
    assert round(summary.net_pnl, 2) == 68.0
    assert round(summary.win_rate, 4) == 0.6667
    assert round(summary.avg_win, 2) == 59.5
    assert round(summary.avg_loss, 2) == -51.0
    assert round(summary.profit_factor, 2) == 2.33
    assert round(summary.expectancy, 2) == 22.67
    assert round(summary.plan_adherence_rate, 4) == 0.6667
    assert round(summary.benchmark_outperformance_rate, 4) == 0.6667
    assert summary.max_consecutive_losses == 1


def test_evaluate_completed_trades_handles_empty_input() -> None:
    summary = evaluate_completed_trades([])

    assert summary.total_trades == 0
    assert summary.net_pnl == 0
    assert summary.warnings == ["No completed trades were provided."]
