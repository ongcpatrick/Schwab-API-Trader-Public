"""SQLite-backed local journal persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

from schwab_trader.journal.models import JournalOverview, StoredCompletedTrade, SyncRunSummary


class SQLiteJournalStore:
    """Persist account, order, transaction, and sync metadata locally."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        if self._database_path != ":memory:":
            Path(self._database_path).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        self._initialize_schema()

    @classmethod
    def from_database_url(cls, database_url: str) -> SQLiteJournalStore:
        """Construct a store from a sqlite database URL."""

        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("Only sqlite database URLs are supported.")
        path = database_url.removeprefix(prefix)
        if path == "/:memory:":
            path = ":memory:"
        return cls(path)

    def upsert_account_snapshot(
        self,
        *,
        account_hash: str,
        masked_account_number: str,
        payload: Mapping[str, object],
        synced_at,
    ) -> None:
        """Upsert the latest account snapshot for a Schwab account hash."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_snapshots (
                    account_hash,
                    masked_account_number,
                    synced_at,
                    raw_json
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_hash) DO UPDATE SET
                    masked_account_number = excluded.masked_account_number,
                    synced_at = excluded.synced_at,
                    raw_json = excluded.raw_json
                """,
                (
                    account_hash,
                    masked_account_number,
                    synced_at.isoformat(),
                    _canonical_json(payload),
                ),
            )

    def upsert_orders(
        self,
        *,
        account_hash: str,
        orders: Sequence[Mapping[str, object]],
        synced_at,
    ) -> int:
        """Upsert order payloads for an account."""

        rows = [
            (
                account_hash,
                _stable_identifier(order.get("orderId"), order),
                _optional_text(order.get("enteredTime")),
                _optional_text(order.get("status")),
                synced_at.isoformat(),
                _canonical_json(order),
            )
            for order in orders
        ]
        if not rows:
            return 0

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO order_snapshots (
                    account_hash,
                    order_id,
                    entered_time,
                    status,
                    synced_at,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_hash, order_id) DO UPDATE SET
                    entered_time = excluded.entered_time,
                    status = excluded.status,
                    synced_at = excluded.synced_at,
                    raw_json = excluded.raw_json
                """,
                rows,
            )
        return len(rows)

    def upsert_transactions(
        self,
        *,
        account_hash: str,
        transactions: Sequence[Mapping[str, object]],
        synced_at,
    ) -> int:
        """Upsert transaction payloads for an account."""

        rows = [
            (
                account_hash,
                _stable_identifier(transaction.get("activityId"), transaction),
                _optional_text(transaction.get("type")),
                _optional_text(transaction.get("tradeDate") or transaction.get("time")),
                _extract_transaction_symbol(transaction),
                synced_at.isoformat(),
                _canonical_json(transaction),
            )
            for transaction in transactions
        ]
        if not rows:
            return 0

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO transaction_snapshots (
                    account_hash,
                    transaction_id,
                    transaction_type,
                    trade_date,
                    symbol,
                    synced_at,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_hash, transaction_id) DO UPDATE SET
                    transaction_type = excluded.transaction_type,
                    trade_date = excluded.trade_date,
                    symbol = excluded.symbol,
                    synced_at = excluded.synced_at,
                    raw_json = excluded.raw_json
                """,
                rows,
            )
        return len(rows)

    def record_sync_run(self, summary: SyncRunSummary) -> None:
        """Persist a sync-run summary."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs (
                    run_id,
                    started_at,
                    completed_at,
                    status,
                    orders_from,
                    orders_to,
                    transactions_from,
                    transactions_to,
                    accounts_synced,
                    orders_synced,
                    transactions_synced,
                    warnings_json,
                    error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    status = excluded.status,
                    orders_from = excluded.orders_from,
                    orders_to = excluded.orders_to,
                    transactions_from = excluded.transactions_from,
                    transactions_to = excluded.transactions_to,
                    accounts_synced = excluded.accounts_synced,
                    orders_synced = excluded.orders_synced,
                    transactions_synced = excluded.transactions_synced,
                    warnings_json = excluded.warnings_json,
                    error_message = excluded.error_message
                """,
                (
                    summary.run_id,
                    summary.started_at.isoformat(),
                    summary.completed_at.isoformat(),
                    summary.status.value,
                    summary.orders_from.isoformat(),
                    summary.orders_to.isoformat(),
                    summary.transactions_from.isoformat(),
                    summary.transactions_to.isoformat(),
                    summary.accounts_synced,
                    summary.orders_synced,
                    summary.transactions_synced,
                    json.dumps(summary.warnings),
                    summary.error_message,
                ),
            )

    def get_overview(self) -> JournalOverview:
        """Return local journal counts and the latest sync run, if present."""

        with self._connect() as connection:
            account_count = connection.execute(
                "SELECT COUNT(*) FROM account_snapshots"
            ).fetchone()[0]
            order_count = connection.execute(
                "SELECT COUNT(*) FROM order_snapshots"
            ).fetchone()[0]
            transaction_count = connection.execute(
                "SELECT COUNT(*) FROM transaction_snapshots"
            ).fetchone()[0]
            last_sync_row = connection.execute(
                """
                SELECT *
                FROM sync_runs
                ORDER BY completed_at DESC, started_at DESC
                LIMIT 1
                """
            ).fetchone()

        return JournalOverview(
            account_count=account_count,
            order_count=order_count,
            transaction_count=transaction_count,
            last_sync=_row_to_sync_run_summary(last_sync_row),
        )

    def list_accounts(self) -> list[dict[str, object]]:
        """List stored account snapshots for local inspection."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account_hash, masked_account_number, synced_at, raw_json
                FROM account_snapshots
                ORDER BY account_hash
                """
            ).fetchall()
        return [
            {
                "account_hash": row["account_hash"],
                "masked_account_number": row["masked_account_number"],
                "synced_at": row["synced_at"],
                "payload": json.loads(row["raw_json"]),
            }
            for row in rows
        ]

    def list_orders(
        self,
        *,
        account_hash: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List stored orders for local inspection."""

        params: list[object] = []
        where_clause = ""
        if account_hash is not None:
            where_clause = "WHERE account_hash = ?"
            params.append(account_hash)
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT account_hash, order_id, entered_time, status, synced_at, raw_json
                FROM order_snapshots
                {where_clause}
                ORDER BY entered_time DESC, order_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "account_hash": row["account_hash"],
                "order_id": row["order_id"],
                "entered_time": row["entered_time"],
                "status": row["status"],
                "synced_at": row["synced_at"],
                "payload": json.loads(row["raw_json"]),
            }
            for row in rows
        ]

    def list_transactions(
        self,
        *,
        account_hash: str | None = None,
        transaction_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List stored transactions for local inspection."""

        clauses: list[str] = []
        params: list[object] = []
        if account_hash is not None:
            clauses.append("account_hash = ?")
            params.append(account_hash)
        if transaction_type is not None:
            clauses.append("transaction_type = ?")
            params.append(transaction_type)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    account_hash,
                    transaction_id,
                    transaction_type,
                    trade_date,
                    symbol,
                    synced_at,
                    raw_json
                FROM transaction_snapshots
                {where_clause}
                ORDER BY trade_date DESC, transaction_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "account_hash": row["account_hash"],
                "transaction_id": row["transaction_id"],
                "transaction_type": row["transaction_type"],
                "trade_date": row["trade_date"],
                "symbol": row["symbol"],
                "synced_at": row["synced_at"],
                "payload": json.loads(row["raw_json"]),
            }
            for row in rows
        ]

    def list_sync_runs(self, *, limit: int = 20) -> list[SyncRunSummary]:
        """List recent sync runs for local inspection."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM sync_runs
                ORDER BY completed_at DESC, started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_sync_run_summary(row) for row in rows if row is not None]

    def load_order_payloads(self) -> list[dict[str, object]]:
        """Load raw order payloads for reconstruction workflows."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account_hash, order_id, raw_json
                FROM order_snapshots
                ORDER BY entered_time ASC, order_id ASC
                """
            ).fetchall()
        return [
            {
                "account_hash": row["account_hash"],
                "order_id": row["order_id"],
                "payload": json.loads(row["raw_json"]),
            }
            for row in rows
        ]

    def load_trade_transaction_payloads(self) -> list[dict[str, object]]:
        """Load raw trade transaction payloads for reconstruction workflows."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account_hash, transaction_id, trade_date, raw_json
                FROM transaction_snapshots
                WHERE transaction_type = 'TRADE'
                ORDER BY trade_date ASC, transaction_id ASC
                """
            ).fetchall()
        return [
            {
                "account_hash": row["account_hash"],
                "transaction_id": row["transaction_id"],
                "trade_date": row["trade_date"],
                "payload": json.loads(row["raw_json"]),
            }
            for row in rows
        ]

    def replace_completed_trades(self, trades: Sequence[StoredCompletedTrade]) -> None:
        """Replace the reconstructed completed-trades table with fresh output."""

        with self._connect() as connection:
            connection.execute("DELETE FROM completed_trades")
            if not trades:
                return
            connection.executemany(
                """
                INSERT INTO completed_trades (
                    trade_id,
                    account_hash,
                    symbol,
                    side,
                    quantity,
                    entry_price,
                    exit_price,
                    gross_pnl,
                    fees,
                    net_pnl,
                    entry_time,
                    exit_time,
                    hold_minutes,
                    benchmark_return_pct,
                    entry_order_id,
                    exit_order_id,
                    entry_transaction_id,
                    exit_transaction_id,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        trade.trade_id,
                        trade.account_hash,
                        trade.symbol,
                        trade.side.value,
                        trade.quantity,
                        trade.entry_price,
                        trade.exit_price,
                        trade.gross_pnl,
                        trade.fees,
                        trade.net_pnl,
                        trade.entry_time.isoformat(),
                        trade.exit_time.isoformat(),
                        trade.hold_minutes,
                        trade.benchmark_return_pct,
                        trade.entry_order_id,
                        trade.exit_order_id,
                        trade.entry_transaction_id,
                        trade.exit_transaction_id,
                        trade.model_dump_json(),
                    )
                    for trade in trades
                ],
            )

    def list_completed_trades(
        self,
        *,
        account_hash: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List reconstructed completed trades for local inspection and scorecards."""

        clauses: list[str] = []
        params: list[object] = []
        if account_hash is not None:
            clauses.append("account_hash = ?")
            params.append(account_hash)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT raw_json
                FROM completed_trades
                {where_clause}
                ORDER BY exit_time DESC, entry_time DESC, trade_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [json.loads(row["raw_json"]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    account_hash TEXT PRIMARY KEY,
                    masked_account_number TEXT NOT NULL,
                    synced_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_snapshots (
                    account_hash TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    entered_time TEXT,
                    status TEXT,
                    synced_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (account_hash, order_id)
                );

                CREATE TABLE IF NOT EXISTS transaction_snapshots (
                    account_hash TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    transaction_type TEXT,
                    trade_date TEXT,
                    symbol TEXT,
                    synced_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (account_hash, transaction_id)
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    orders_from TEXT NOT NULL,
                    orders_to TEXT NOT NULL,
                    transactions_from TEXT NOT NULL,
                    transactions_to TEXT NOT NULL,
                    accounts_synced INTEGER NOT NULL,
                    orders_synced INTEGER NOT NULL,
                    transactions_synced INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS completed_trades (
                    trade_id TEXT PRIMARY KEY,
                    account_hash TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    gross_pnl REAL NOT NULL,
                    fees REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    hold_minutes INTEGER,
                    benchmark_return_pct REAL,
                    entry_order_id TEXT,
                    exit_order_id TEXT,
                    entry_transaction_id TEXT,
                    exit_transaction_id TEXT,
                    raw_json TEXT NOT NULL
                );
                """
            )


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _stable_identifier(value: object, payload: Mapping[str, object]) -> str:
    if value is not None:
        return str(value)
    digest = hashlib.sha1(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"generated-{digest}"


def _extract_transaction_symbol(transaction: Mapping[str, object]) -> str | None:
    transfer_items = transaction.get("transferItems")
    if not isinstance(transfer_items, list):
        return None
    for item in transfer_items:
        if not isinstance(item, Mapping):
            continue
        instrument = item.get("instrument")
        if not isinstance(instrument, Mapping):
            continue
        symbol = instrument.get("symbol")
        if symbol is not None:
            return str(symbol)
    return None


def _row_to_sync_run_summary(row: sqlite3.Row | None) -> SyncRunSummary | None:
    if row is None:
        return None
    return SyncRunSummary.model_validate(
        {
            "run_id": row["run_id"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "orders_from": row["orders_from"],
            "orders_to": row["orders_to"],
            "transactions_from": row["transactions_from"],
            "transactions_to": row["transactions_to"],
            "accounts_synced": row["accounts_synced"],
            "orders_synced": row["orders_synced"],
            "transactions_synced": row["transactions_synced"],
            "warnings": json.loads(row["warnings_json"]),
            "error_message": row["error_message"],
        }
    )
