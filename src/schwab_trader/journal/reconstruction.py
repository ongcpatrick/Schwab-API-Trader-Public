"""Completed-trade reconstruction from raw order and transaction snapshots."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from schwab_trader.journal.metrics import build_trade_scorecard
from schwab_trader.journal.models import (
    CompletedTradeRebuildSummary,
    StoredCompletedTrade,
    TradeScorecard,
    TradeSide,
)
from schwab_trader.journal.store import SQLiteJournalStore


@dataclass
class _TradeEvent:
    account_hash: str
    transaction_id: str
    order_id: str | None
    symbol: str
    quantity: float
    direction: int
    price: float
    fees: float
    trade_time: datetime


@dataclass
class _OpenLot:
    account_hash: str
    symbol: str
    direction: int
    quantity: float
    price: float
    trade_time: datetime
    fee_per_share: float
    order_id: str | None
    transaction_id: str | None


class CompletedTradeRebuilder:
    """Reconstruct normalized completed trades from raw synced Schwab data."""

    def __init__(self, *, store: SQLiteJournalStore) -> None:
        self._store = store

    def rebuild(self) -> CompletedTradeRebuildSummary:
        """Rebuild the completed-trades table from raw order and transaction snapshots."""

        orders = self._store.load_order_payloads()
        transactions = self._store.load_trade_transaction_payloads()
        order_lookup = _build_order_lookup(orders)

        warnings: list[str] = []
        events: list[_TradeEvent] = []
        for transaction in transactions:
            try:
                events.append(_event_from_transaction(transaction, order_lookup))
            except ValueError as exc:
                warnings.append(str(exc))

        completed_trades, open_lot_count = _match_completed_trades(events)
        self._store.replace_completed_trades(completed_trades)
        return CompletedTradeRebuildSummary(
            completed_trade_count=len(completed_trades),
            open_lot_count=open_lot_count,
            warnings=warnings,
        )


class TradeScorecardService:
    """Build scorecards from reconstructed completed trades."""

    def __init__(self, *, store: SQLiteJournalStore) -> None:
        self._store = store

    def build_scorecard(
        self,
        *,
        account_hash: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
    ) -> TradeScorecard:
        """Build a scorecard from reconstructed completed trades."""

        stored = self._store.list_completed_trades(
            account_hash=account_hash,
            symbol=symbol,
            limit=limit,
        )
        trades = [StoredCompletedTrade.model_validate(item) for item in stored]
        return build_trade_scorecard(trades)


def _build_order_lookup(order_rows: list[dict[str, object]]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for row in order_rows:
        payload = row["payload"]
        if not isinstance(payload, Mapping):
            continue
        order_id = row["order_id"]
        account_hash = row["account_hash"]
        if not isinstance(order_id, str) or not isinstance(account_hash, str):
            continue
        legs = payload.get("orderLegCollection")
        if not isinstance(legs, list) or not legs:
            continue
        first_leg = legs[0]
        if not isinstance(first_leg, Mapping):
            continue
        instruction = first_leg.get("instruction")
        if instruction is not None:
            lookup[(account_hash, order_id)] = str(instruction)
    return lookup


def _event_from_transaction(
    transaction_row: dict[str, object],
    order_lookup: dict[tuple[str, str], str],
) -> _TradeEvent:
    payload = transaction_row["payload"]
    if not isinstance(payload, Mapping):
        raise ValueError("Skipping malformed transaction payload during reconstruction.")

    account_hash = str(transaction_row["account_hash"])
    transaction_id = str(transaction_row["transaction_id"])
    order_id = payload.get("orderId")
    order_id_text = None if order_id is None else str(order_id)
    instruction = None
    if order_id_text is not None:
        instruction = order_lookup.get((account_hash, order_id_text))

    transfer_items = payload.get("transferItems")
    if not isinstance(transfer_items, list) or not transfer_items:
        raise ValueError(f"Skipping transaction {transaction_id}: no transfer items were present.")

    symbol = None
    total_quantity = 0.0
    total_notional = 0.0
    position_effect = None
    for item in transfer_items:
        if not isinstance(item, Mapping):
            continue
        instrument = item.get("instrument")
        if (
            isinstance(instrument, Mapping)
            and instrument.get("symbol") is not None
            and symbol is None
        ):
            symbol = str(instrument["symbol"])
        if position_effect is None and item.get("positionEffect") is not None:
            position_effect = str(item["positionEffect"])
        amount = item.get("amount")
        price = item.get("price")
        if amount is None or price is None:
            continue
        quantity = abs(float(amount))
        total_quantity += quantity
        total_notional += quantity * float(price)

    if symbol is None:
        raise ValueError(f"Skipping transaction {transaction_id}: no symbol could be identified.")
    if total_quantity <= 0:
        raise ValueError(
            f"Skipping transaction {transaction_id}: no executable quantity was found."
        )

    direction = _resolve_direction(instruction, payload.get("netAmount"), position_effect)
    if direction == 0:
        raise ValueError(
            f"Skipping transaction {transaction_id}: trade direction could not be inferred."
        )

    price = total_notional / total_quantity
    fees = _estimate_transaction_fees(total_notional, payload.get("netAmount"))
    trade_time = _parse_datetime(
        payload.get("tradeDate") or payload.get("time") or transaction_row.get("trade_date")
    )

    return _TradeEvent(
        account_hash=account_hash,
        transaction_id=transaction_id,
        order_id=order_id_text,
        symbol=symbol,
        quantity=total_quantity,
        direction=direction,
        price=price,
        fees=fees,
        trade_time=trade_time,
    )


def _resolve_direction(
    instruction: str | None,
    net_amount: object,
    position_effect: str | None,
) -> int:
    buy_instructions = {"BUY", "BUY_TO_OPEN", "BUY_TO_COVER"}
    sell_instructions = {"SELL", "SELL_SHORT", "SELL_TO_OPEN", "SELL_TO_CLOSE"}

    if instruction is not None:
        normalized = instruction.upper()
        if normalized in buy_instructions:
            return 1
        if normalized in sell_instructions:
            return -1

    if net_amount is None:
        return 0
    amount = float(net_amount)
    if amount < 0:
        return 1
    if amount > 0:
        return -1
    if position_effect == "OPENING":
        return -1
    if position_effect == "CLOSING":
        return 1
    return 0


def _estimate_transaction_fees(total_notional: float, net_amount: object) -> float:
    if net_amount is None:
        return 0.0
    return max(abs(abs(float(net_amount)) - total_notional), 0.0)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Expected ISO-8601 datetime text.")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _match_completed_trades(
    events: list[_TradeEvent],
) -> tuple[list[StoredCompletedTrade], int]:
    lots: dict[tuple[str, str], deque[_OpenLot]] = defaultdict(deque)
    completed: list[StoredCompletedTrade] = []

    for event in sorted(events, key=lambda item: (item.trade_time, item.transaction_id)):
        key = (event.account_hash, event.symbol)
        event_quantity_remaining = event.quantity
        event_fee_per_share = event.fees / event.quantity if event.quantity else 0.0
        queue = lots[key]

        while event_quantity_remaining > 0 and queue and queue[0].direction != event.direction:
            lot = queue[0]
            matched_quantity = min(event_quantity_remaining, lot.quantity)
            entry_fee = lot.fee_per_share * matched_quantity
            exit_fee = event_fee_per_share * matched_quantity
            completed.append(
                _build_completed_trade(
                    lot=lot,
                    exit_event=event,
                    matched_quantity=matched_quantity,
                    total_fees=entry_fee + exit_fee,
                    match_index=len(completed),
                )
            )
            lot.quantity -= matched_quantity
            event_quantity_remaining -= matched_quantity
            if lot.quantity <= 0:
                queue.popleft()

        if event_quantity_remaining > 0:
            queue.append(
                _OpenLot(
                    account_hash=event.account_hash,
                    symbol=event.symbol,
                    direction=event.direction,
                    quantity=event_quantity_remaining,
                    price=event.price,
                    trade_time=event.trade_time,
                    fee_per_share=event_fee_per_share,
                    order_id=event.order_id,
                    transaction_id=event.transaction_id,
                )
            )

    open_lot_count = sum(len(queue) for queue in lots.values())
    completed.sort(key=lambda trade: (trade.exit_time, trade.trade_id), reverse=True)
    return completed, open_lot_count


def _build_completed_trade(
    *,
    lot: _OpenLot,
    exit_event: _TradeEvent,
    matched_quantity: float,
    total_fees: float,
    match_index: int,
) -> StoredCompletedTrade:
    side = TradeSide.LONG if lot.direction > 0 else TradeSide.SHORT
    gross_pnl = (
        (exit_event.price - lot.price) * matched_quantity
        if side is TradeSide.LONG
        else (lot.price - exit_event.price) * matched_quantity
    )
    hold_minutes = max(
        int((exit_event.trade_time - lot.trade_time).total_seconds() // 60),
        0,
    )
    trade_id = hashlib.sha1(
        (
            f"{lot.account_hash}|{lot.symbol}|{lot.transaction_id}|{exit_event.transaction_id}|"
            f"{matched_quantity}|{match_index}"
        ).encode()
    ).hexdigest()
    return StoredCompletedTrade(
        trade_id=trade_id,
        account_hash=lot.account_hash,
        symbol=lot.symbol,
        side=side,
        quantity=matched_quantity,
        entry_price=lot.price,
        exit_price=exit_event.price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=gross_pnl - total_fees,
        entry_time=lot.trade_time,
        exit_time=exit_event.trade_time,
        hold_minutes=hold_minutes,
        entry_order_id=lot.order_id,
        exit_order_id=exit_event.order_id,
        entry_transaction_id=lot.transaction_id,
        exit_transaction_id=exit_event.transaction_id,
        benchmark_return_pct=None,
    )
