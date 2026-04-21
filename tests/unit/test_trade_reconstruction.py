from datetime import UTC, datetime
from pathlib import Path

from schwab_trader.journal.models import TradeSide
from schwab_trader.journal.reconstruction import CompletedTradeRebuilder
from schwab_trader.journal.store import SQLiteJournalStore


def test_rebuilder_creates_completed_long_trade_from_orders_and_transactions(
    tmp_path: Path,
) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    synced_at = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)

    store.upsert_orders(
        account_hash="hash-123",
        orders=[
            {
                "orderId": 1001,
                "orderLegCollection": [
                    {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                ],
            },
            {
                "orderId": 1002,
                "orderLegCollection": [
                    {"instruction": "SELL", "instrument": {"symbol": "AAPL"}},
                ],
            },
        ],
        synced_at=synced_at,
    )
    store.upsert_transactions(
        account_hash="hash-123",
        transactions=[
            {
                "activityId": 2001,
                "orderId": 1001,
                "type": "TRADE",
                "tradeDate": "2026-04-01T14:30:00.000Z",
                "netAmount": -1000,
                "transferItems": [
                    {
                        "amount": 10,
                        "price": 100,
                        "positionEffect": "OPENING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
            {
                "activityId": 2002,
                "orderId": 1002,
                "type": "TRADE",
                "tradeDate": "2026-04-03T14:30:00.000Z",
                "netAmount": 1100,
                "transferItems": [
                    {
                        "amount": 10,
                        "price": 110,
                        "positionEffect": "CLOSING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
        ],
        synced_at=synced_at,
    )

    summary = CompletedTradeRebuilder(store=store).rebuild()
    trades = store.list_completed_trades()

    assert summary.completed_trade_count == 1
    assert summary.open_lot_count == 0
    assert trades[0]["symbol"] == "AAPL"
    assert trades[0]["side"] == TradeSide.LONG
    assert trades[0]["quantity"] == 10
    assert trades[0]["entry_price"] == 100
    assert trades[0]["exit_price"] == 110
    assert trades[0]["gross_pnl"] == 100


def test_rebuilder_uses_fifo_for_partial_exits(tmp_path: Path) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    synced_at = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)

    store.upsert_orders(
        account_hash="hash-123",
        orders=[
            {
                "orderId": 1001,
                "orderLegCollection": [
                    {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                ],
            },
            {
                "orderId": 1002,
                "orderLegCollection": [
                    {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                ],
            },
            {
                "orderId": 1003,
                "orderLegCollection": [
                    {"instruction": "SELL", "instrument": {"symbol": "AAPL"}},
                ],
            },
        ],
        synced_at=synced_at,
    )
    store.upsert_transactions(
        account_hash="hash-123",
        transactions=[
            {
                "activityId": 2001,
                "orderId": 1001,
                "type": "TRADE",
                "tradeDate": "2026-04-01T14:30:00.000Z",
                "netAmount": -1000,
                "transferItems": [
                    {
                        "amount": 10,
                        "price": 100,
                        "positionEffect": "OPENING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
            {
                "activityId": 2002,
                "orderId": 1002,
                "type": "TRADE",
                "tradeDate": "2026-04-02T14:30:00.000Z",
                "netAmount": -600,
                "transferItems": [
                    {
                        "amount": 5,
                        "price": 120,
                        "positionEffect": "OPENING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
            {
                "activityId": 2003,
                "orderId": 1003,
                "type": "TRADE",
                "tradeDate": "2026-04-03T14:30:00.000Z",
                "netAmount": 1560,
                "transferItems": [
                    {
                        "amount": 12,
                        "price": 130,
                        "positionEffect": "CLOSING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
        ],
        synced_at=synced_at,
    )

    summary = CompletedTradeRebuilder(store=store).rebuild()
    trades = store.list_completed_trades(symbol="AAPL", limit=10)

    assert summary.completed_trade_count == 2
    assert summary.open_lot_count == 1
    assert trades[0]["quantity"] == 2
    assert trades[0]["entry_price"] == 120
    assert trades[0]["exit_price"] == 130
    assert trades[1]["quantity"] == 10
    assert trades[1]["entry_price"] == 100
    assert trades[1]["exit_price"] == 130


def test_rebuilder_infers_short_trade_direction_without_order_snapshot(tmp_path: Path) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    synced_at = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)

    store.upsert_transactions(
        account_hash="hash-123",
        transactions=[
            {
                "activityId": 3001,
                "type": "TRADE",
                "tradeDate": "2026-04-01T14:30:00.000Z",
                "netAmount": 250,
                "transferItems": [
                    {
                        "amount": 5,
                        "price": 50,
                        "positionEffect": "OPENING",
                        "instrument": {"symbol": "TSLA"},
                    }
                ],
            },
            {
                "activityId": 3002,
                "type": "TRADE",
                "tradeDate": "2026-04-02T14:30:00.000Z",
                "netAmount": -225,
                "transferItems": [
                    {
                        "amount": 5,
                        "price": 45,
                        "positionEffect": "CLOSING",
                        "instrument": {"symbol": "TSLA"},
                    }
                ],
            },
        ],
        synced_at=synced_at,
    )

    summary = CompletedTradeRebuilder(store=store).rebuild()
    trades = store.list_completed_trades(symbol="TSLA", limit=10)

    assert summary.completed_trade_count == 1
    assert trades[0]["side"] == TradeSide.SHORT
    assert trades[0]["gross_pnl"] == 25
    assert trades[0]["net_pnl"] == 25
