"""Command-line entrypoints for local journal sync workflows."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from schwab_trader.core.settings import get_settings
from schwab_trader.journal.store import SQLiteJournalStore
from schwab_trader.journal.sync import DEFAULT_TRANSACTION_TYPES, JournalSyncService
from schwab_trader.server.dependencies import get_broker_service


def create_journal_store() -> SQLiteJournalStore:
    """Build the configured local journal store."""

    settings = get_settings()
    return SQLiteJournalStore.from_database_url(settings.journal_database_url)


def create_sync_service() -> JournalSyncService:
    """Build the configured local sync service."""

    return JournalSyncService(
        broker_service=get_broker_service(),
        store=create_journal_store(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local CLI."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "sync":
        return _run_sync_command(args)
    if args.command == "status":
        return _run_status_command()
    parser.error("Unknown command.")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="schwab-trader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync Schwab data into the local journal.",
    )
    sync_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="How many days of history to sync.",
    )
    sync_parser.add_argument(
        "--transaction-types",
        default=",".join(DEFAULT_TRANSACTION_TYPES),
        help="Comma-separated Schwab transaction types to sync.",
    )

    subparsers.add_parser("status", help="Show local journal counts and the latest sync status.")
    return parser


def _run_sync_command(args: argparse.Namespace) -> int:
    if args.days <= 0:
        raise SystemExit("--days must be greater than zero.")

    service = create_sync_service()
    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)
    transaction_types = [item.strip() for item in args.transaction_types.split(",") if item.strip()]

    summary = service.sync(
        orders_from=start,
        orders_to=now,
        transactions_from=start,
        transactions_to=now,
        transaction_types=transaction_types,
    )

    print("Sync completed.")
    print(f"Run ID: {summary.run_id}")
    print(f"Accounts synced: {summary.accounts_synced}")
    print(f"Orders synced: {summary.orders_synced}")
    print(f"Transactions synced: {summary.transactions_synced}")
    if summary.warnings:
        print("Warnings:")
        for warning in summary.warnings:
            print(f"- {warning}")
    return 0


def _run_status_command() -> int:
    overview = create_journal_store().get_overview()

    print(f"Accounts stored: {overview.account_count}")
    print(f"Orders stored: {overview.order_count}")
    print(f"Transactions stored: {overview.transaction_count}")
    if overview.last_sync is None:
        print("Last sync: none")
        return 0

    print(f"Last sync status: {overview.last_sync.status.value}")
    print(f"Last sync completed at: {overview.last_sync.completed_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
