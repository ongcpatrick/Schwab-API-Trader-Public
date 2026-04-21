"""Local sync orchestration for Schwab account data."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.journal.models import SyncRunStatus, SyncRunSummary
from schwab_trader.journal.reconstruction import CompletedTradeRebuilder
from schwab_trader.journal.store import SQLiteJournalStore

DEFAULT_TRANSACTION_TYPES = (
    "TRADE",
    "RECEIVE_AND_DELIVER",
    "DIVIDEND_OR_INTEREST",
    "ACH_RECEIPT",
    "ACH_DISBURSEMENT",
    "CASH_RECEIPT",
    "CASH_DISBURSEMENT",
    "ELECTRONIC_FUND",
    "WIRE_OUT",
    "WIRE_IN",
    "JOURNAL",
    "MEMORANDUM",
    "MARGIN_CALL",
    "MONEY_MARKET",
    "SMA_ADJUSTMENT",
)


class JournalSyncService:
    """Sync Schwab account snapshots into the local journal store."""

    def __init__(self, *, broker_service: SchwabBrokerService, store: SQLiteJournalStore) -> None:
        self._broker_service = broker_service
        self._store = store

    def sync(
        self,
        *,
        orders_from: datetime,
        orders_to: datetime,
        transactions_from: datetime,
        transactions_to: datetime,
        transaction_types: list[str] | tuple[str, ...] = DEFAULT_TRANSACTION_TYPES,
    ) -> SyncRunSummary:
        """Run a local account, order, and transaction sync."""

        started_at = datetime.now(UTC)
        run_id = uuid4().hex
        warnings: list[str] = []
        accounts_synced = 0
        orders_synced = 0
        transactions_synced = 0

        try:
            account_numbers = self._broker_service.get_account_numbers()
            if not account_numbers:
                warnings.append("No linked Schwab accounts were returned.")

            for account_mapping in account_numbers:
                account_hash = str(account_mapping["hashValue"])
                account_number = str(account_mapping["accountNumber"])
                masked_account_number = mask_account_number(account_number)
                synced_at = datetime.now(UTC)

                account_payload = self._broker_service.get_account(
                    account_hash,
                    fields=["positions"],
                )
                self._store.upsert_account_snapshot(
                    account_hash=account_hash,
                    masked_account_number=masked_account_number,
                    payload=account_payload,
                    synced_at=synced_at,
                )
                accounts_synced += 1

                orders = self._broker_service.get_orders_for_account(
                    account_hash=account_hash,
                    from_entered_time=format_schwab_datetime(orders_from),
                    to_entered_time=format_schwab_datetime(orders_to),
                )
                orders_synced += self._store.upsert_orders(
                    account_hash=account_hash,
                    orders=orders,
                    synced_at=synced_at,
                )
                if len(orders) == 3000:
                    warnings.append(
                        "Orders for account "
                        f"{masked_account_number} hit the 3000-record response cap."
                    )

                transactions = self._broker_service.get_transactions(
                    account_hash=account_hash,
                    start_date=format_schwab_datetime(transactions_from),
                    end_date=format_schwab_datetime(transactions_to),
                    types=transaction_types,
                )
                transactions_synced += self._store.upsert_transactions(
                    account_hash=account_hash,
                    transactions=transactions,
                    synced_at=synced_at,
                )
                if len(transactions) == 3000:
                    warnings.append(
                        "Transactions for account "
                        f"{masked_account_number} hit the 3000-record response cap."
                    )

            summary = SyncRunSummary(
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                status=SyncRunStatus.SUCCESS,
                orders_from=orders_from,
                orders_to=orders_to,
                transactions_from=transactions_from,
                transactions_to=transactions_to,
                accounts_synced=accounts_synced,
                orders_synced=orders_synced,
                transactions_synced=transactions_synced,
                warnings=warnings,
            )
            rebuild_summary = CompletedTradeRebuilder(store=self._store).rebuild()
            summary.warnings.extend(rebuild_summary.warnings)
            if rebuild_summary.open_lot_count:
                summary.warnings.append(
                    "Completed-trade reconstruction left "
                    f"{rebuild_summary.open_lot_count} open lot(s) unmatched."
                )
            self._store.record_sync_run(summary)
            return summary
        except Exception as exc:
            failed_summary = SyncRunSummary(
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                status=SyncRunStatus.FAILED,
                orders_from=orders_from,
                orders_to=orders_to,
                transactions_from=transactions_from,
                transactions_to=transactions_to,
                accounts_synced=accounts_synced,
                orders_synced=orders_synced,
                transactions_synced=transactions_synced,
                warnings=warnings,
                error_message=str(exc),
            )
            self._store.record_sync_run(failed_summary)
            raise


def format_schwab_datetime(value: datetime) -> str:
    """Format datetimes for Schwab ISO-8601 query parameters."""

    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mask_account_number(account_number: str) -> str:
    """Return a masked local representation of an account number."""

    if not account_number:
        return "unknown"
    if len(account_number) <= 4:
        return account_number
    return f"{'*' * (len(account_number) - 4)}{account_number[-4:]}"
