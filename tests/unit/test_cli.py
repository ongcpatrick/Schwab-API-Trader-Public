from datetime import UTC, datetime

from schwab_trader import cli
from schwab_trader.journal.models import JournalOverview, SyncRunStatus, SyncRunSummary


def test_cli_sync_command_prints_summary(monkeypatch, capsys) -> None:
    class StubSyncService:
        def sync(self, **kwargs) -> SyncRunSummary:
            assert kwargs["transaction_types"] == ["TRADE", "DIVIDEND_OR_INTEREST"]
            now = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)
            return SyncRunSummary(
                run_id="run-123",
                started_at=now,
                completed_at=now,
                status=SyncRunStatus.SUCCESS,
                orders_from=now,
                orders_to=now,
                transactions_from=now,
                transactions_to=now,
                accounts_synced=2,
                orders_synced=5,
                transactions_synced=7,
            )

    monkeypatch.setattr(cli, "create_sync_service", lambda: StubSyncService())

    exit_code = cli.main(
        ["sync", "--days", "14", "--transaction-types", "TRADE,DIVIDEND_OR_INTEREST"]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Sync completed." in output
    assert "Accounts synced: 2" in output
    assert "Transactions synced: 7" in output


def test_cli_status_command_prints_local_overview(monkeypatch, capsys) -> None:
    now = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)
    overview = JournalOverview(
        account_count=1,
        order_count=4,
        transaction_count=6,
        last_sync=SyncRunSummary(
            run_id="run-123",
            started_at=now,
            completed_at=now,
            status=SyncRunStatus.SUCCESS,
            orders_from=now,
            orders_to=now,
            transactions_from=now,
            transactions_to=now,
            accounts_synced=1,
            orders_synced=4,
            transactions_synced=6,
        ),
    )

    class StubStore:
        def get_overview(self) -> JournalOverview:
            return overview

    monkeypatch.setattr(cli, "create_journal_store", lambda: StubStore())

    exit_code = cli.main(["status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Accounts stored: 1" in output
    assert "Last sync status: success" in output
