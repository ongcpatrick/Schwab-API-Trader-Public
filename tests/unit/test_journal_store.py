from datetime import UTC, datetime
from pathlib import Path

from schwab_trader.journal.models import SyncRunStatus, SyncRunSummary
from schwab_trader.journal.store import SQLiteJournalStore


def test_sqlite_journal_store_persists_snapshots_and_reports_overview(tmp_path: Path) -> None:
    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    synced_at = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)

    store.upsert_account_snapshot(
        account_hash="hash-123",
        masked_account_number="****5678",
        payload={"securitiesAccount": {"accountNumber": "hash-123", "positions": []}},
        synced_at=synced_at,
    )
    store.upsert_orders(
        account_hash="hash-123",
        orders=[{"orderId": 101, "enteredTime": "2026-04-14T19:40:18.901Z", "status": "FILLED"}],
        synced_at=synced_at,
    )
    store.upsert_transactions(
        account_hash="hash-123",
        transactions=[
            {
                "activityId": 202,
                "type": "TRADE",
                "tradeDate": "2026-04-14T19:40:18.927Z",
                "transferItems": [{"instrument": {"symbol": "AAPL"}}],
            }
        ],
        synced_at=synced_at,
    )

    summary = SyncRunSummary(
        run_id="run-123",
        started_at=synced_at,
        completed_at=synced_at,
        status=SyncRunStatus.SUCCESS,
        orders_from=synced_at,
        orders_to=synced_at,
        transactions_from=synced_at,
        transactions_to=synced_at,
        accounts_synced=1,
        orders_synced=1,
        transactions_synced=1,
    )
    store.record_sync_run(summary)

    overview = store.get_overview()
    accounts = store.list_accounts()
    orders = store.list_orders()
    transactions = store.list_transactions()

    assert overview.account_count == 1
    assert overview.order_count == 1
    assert overview.transaction_count == 1
    assert overview.last_sync is not None
    assert overview.last_sync.status is SyncRunStatus.SUCCESS
    assert accounts == [
        {
            "account_hash": "hash-123",
            "masked_account_number": "****5678",
            "synced_at": synced_at.isoformat(),
            "payload": {"securitiesAccount": {"accountNumber": "hash-123", "positions": []}},
        }
    ]
    assert orders[0]["order_id"] == "101"
    assert orders[0]["status"] == "FILLED"
    assert transactions[0]["transaction_id"] == "202"
    assert transactions[0]["symbol"] == "AAPL"
