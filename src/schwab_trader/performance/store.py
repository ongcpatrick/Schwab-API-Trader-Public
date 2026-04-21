"""SQLite store for daily portfolio performance snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class PerformanceStore:
    """Persist one portfolio snapshot per calendar day."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        if db_path != ":memory:":
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── schema ────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._conn() as cx:
            cx.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    date              TEXT PRIMARY KEY,  -- YYYY-MM-DD
                    timestamp         TEXT NOT NULL,      -- ISO-8601 datetime
                    portfolio_value   REAL NOT NULL,      -- total liquidation value ($)
                    cash_value        REAL NOT NULL DEFAULT 0,
                    spy_close         REAL,               -- SPY closing price
                    qqq_close         REAL,               -- QQQ closing price
                    positions_json    TEXT                -- JSON snapshot of positions
                )
            """)

    # ── writes ────────────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        date: str,
        timestamp: str,
        portfolio_value: float,
        cash_value: float = 0.0,
        spy_close: float | None = None,
        qqq_close: float | None = None,
        positions: list[dict] | None = None,
    ) -> None:
        """Insert or replace the snapshot for this calendar date."""
        with self._conn() as cx:
            cx.execute(
                """
                INSERT INTO portfolio_snapshots
                    (date, timestamp, portfolio_value, cash_value, spy_close, qqq_close, positions_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    timestamp       = excluded.timestamp,
                    portfolio_value = excluded.portfolio_value,
                    cash_value      = excluded.cash_value,
                    spy_close       = COALESCE(excluded.spy_close, spy_close),
                    qqq_close       = COALESCE(excluded.qqq_close, qqq_close),
                    positions_json  = excluded.positions_json
                """,
                (
                    date,
                    timestamp,
                    portfolio_value,
                    cash_value,
                    spy_close,
                    qqq_close,
                    json.dumps(positions) if positions else None,
                ),
            )

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_all(self, *, limit: int | None = None) -> list[dict]:
        """Return snapshots ordered oldest → newest."""
        sql = "SELECT * FROM portfolio_snapshots ORDER BY date ASC"
        if limit:
            sql += f" LIMIT {limit}"
        with self._conn() as cx:
            rows = cx.execute(sql).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_since(self, since_date: str) -> list[dict]:
        """Return snapshots from since_date (inclusive) onward."""
        with self._conn() as cx:
            rows = cx.execute(
                "SELECT * FROM portfolio_snapshots WHERE date >= ? ORDER BY date ASC",
                (since_date,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_latest(self) -> dict | None:
        """Return the most recent snapshot, or None if empty."""
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def count(self) -> int:
        with self._conn() as cx:
            return cx.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, detect_types=sqlite3.PARSE_DECLTYPES)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | tuple) -> dict:
        keys = ["date", "timestamp", "portfolio_value", "cash_value",
                "spy_close", "qqq_close", "positions_json"]
        d = dict(zip(keys, row))
        if d.get("positions_json"):
            try:
                d["positions"] = json.loads(d["positions_json"])
            except Exception:
                d["positions"] = []
        else:
            d["positions"] = []
        del d["positions_json"]
        return d
