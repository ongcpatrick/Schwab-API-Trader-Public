from datetime import UTC, datetime
from pathlib import Path

import pytest

from schwab_trader.journal.models import SyncRunStatus
from schwab_trader.journal.store import SQLiteJournalStore
from schwab_trader.journal.sync import JournalSyncService


class StubBrokerService:
    def __init__(self) -> None:
        self.account_calls: list[tuple[str, tuple[str, ...]]] = []
        self.order_calls: list[tuple[str, str, str]] = []
        self.transaction_calls: list[tuple[str, str, str, tuple[str, ...]]] = []

    def get_account_numbers(self) -> list[dict]:
        return [{"accountNumber": "12345678", "hashValue": "hash-123"}]

    def get_account(self, account_hash: str, *, fields=None) -> dict:
        self.account_calls.append((account_hash, tuple(fields or ())))
        return {"securitiesAccount": {"accountNumber": account_hash, "positions": []}}

    def get_orders_for_account(
        self,
        *,
        account_hash: str,
        from_entered_time: str,
        to_entered_time: str,
        max_results=None,
        status=None,
    ) -> list[dict]:
        self.order_calls.append((account_hash, from_entered_time, to_entered_time))
        return [
            {
                "orderId": 101,
                "enteredTime": from_entered_time,
                "status": "FILLED",
                "orderLegCollection": [
                    {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                ],
            },
            {
                "orderId": 102,
                "enteredTime": to_entered_time,
                "status": "FILLED",
                "orderLegCollection": [
                    {"instruction": "SELL", "instrument": {"symbol": "AAPL"}},
                ],
            },
        ]

    def get_transactions(
        self,
        *,
        account_hash: str,
        start_date: str,
        end_date: str,
        types,
        symbol=None,
    ) -> list[dict]:
        self.transaction_calls.append((account_hash, start_date, end_date, tuple(types)))
        return [
            {
                "activityId": 202,
                "orderId": 101,
                "type": "TRADE",
                "tradeDate": start_date,
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
                "activityId": 203,
                "orderId": 102,
                "type": "TRADE",
                "tradeDate": end_date,
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
        ]


class FailingBrokerService(StubBrokerService):
    def get_account(self, account_hash: str, *, fields=None) -> dict:
        raise RuntimeError("boom")


def test_sync_service_persists_accounts_orders_and_transactions(tmp_path: Path) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    broker = StubBrokerService()
    service = JournalSyncService(broker_service=broker, store=store)
    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 14, 23, 59, tzinfo=UTC)

    summary = service.sync(
        orders_from=start,
        orders_to=end,
        transactions_from=start,
        transactions_to=end,
        transaction_types=["TRADE"],
    )

    overview = store.get_overview()
    accounts = store.list_accounts()

    assert broker.account_calls == [("hash-123", ("positions",))]
    assert broker.order_calls[0][1].endswith("Z")
    assert broker.transaction_calls[0][3] == ("TRADE",)
    assert summary.status is SyncRunStatus.SUCCESS
    assert summary.accounts_synced == 1
    assert summary.orders_synced == 2
    assert summary.transactions_synced == 2
    assert overview.last_sync is not None
    assert overview.last_sync.status is SyncRunStatus.SUCCESS
    assert accounts[0]["masked_account_number"] == "****5678"
    assert store.list_completed_trades(limit=10)[0]["symbol"] == "AAPL"


def test_sync_service_records_failed_runs(tmp_path: Path) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    service = JournalSyncService(broker_service=FailingBrokerService(), store=store)
    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 14, 23, 59, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="boom"):
        service.sync(
            orders_from=start,
            orders_to=end,
            transactions_from=start,
            transactions_to=end,
            transaction_types=["TRADE"],
        )

    overview = store.get_overview()

    assert overview.last_sync is not None
    assert overview.last_sync.status is SyncRunStatus.FAILED
    assert overview.last_sync.error_message == "boom"
