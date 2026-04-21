"""Guarded execution flow for proposal-backed live orders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.execution.audit import ExecutionAuditStore
from schwab_trader.risk.engine import check_order
from schwab_trader.risk.models import (
    AccountSnapshot,
    OrderIntent,
    OrderType,
    PositionSnapshot,
    RiskPolicy,
    TradeAction,
)


class ProposalExecutionError(Exception):
    """Controlled execution failure with an HTTP-friendly status."""

    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ExecutionService:
    """Run the full risk/preview/place sequence for a proposal."""

    def __init__(
        self,
        *,
        broker_service: SchwabBrokerService,
        settings: Any,
        audit_store: ExecutionAuditStore,
    ) -> None:
        self._broker = broker_service
        self._settings = settings
        self._audit = audit_store

    def execute_proposal(self, proposal: dict, *, source: str) -> dict:
        """Execute one proposal after all guards pass."""

        order_payload = build_order_payload(proposal)
        audit_event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source,
            "proposal_id": proposal.get("id"),
            "symbol": proposal.get("symbol"),
            "action": proposal.get("action"),
            "order_payload": order_payload,
        }

        if getattr(self._settings, "live_order_kill_switch", False):
            self._audit.append({**audit_event, "status": "blocked", "reason": "kill_switch"})
            raise ProposalExecutionError(
                status_code=503,
                detail="Live order execution is disabled by the kill switch.",
            )

        account_hash = self._broker.get_primary_account_hash()
        account = self._broker.get_account(account_hash, fields=["positions"])
        account_snapshot = _build_account_snapshot(account)
        order_intent = _build_order_intent(self._broker, proposal)
        risk_policy = _build_risk_policy(self._settings, proposal)
        risk_result = check_order(order=order_intent, policy=risk_policy, account=account_snapshot)

        if not risk_result.allowed:
            detail = "; ".join(risk_result.reasons)
            self._audit.append(
                {
                    **audit_event,
                    "status": "blocked",
                    "reason": "risk_policy",
                    "risk_check": risk_result.model_dump(mode="json"),
                }
            )
            raise ProposalExecutionError(status_code=409, detail=detail)

        try:
            preview = self._broker.preview_order(
                account_hash=account_hash,
                order_payload=order_payload,
            )
        except Exception as exc:
            self._audit.append(
                {
                    **audit_event,
                    "status": "failed",
                    "reason": "preview_error",
                    "error": str(exc),
                    "risk_check": risk_result.model_dump(mode="json"),
                }
            )
            raise ProposalExecutionError(
                status_code=502,
                detail=f"Order preview failed: {exc}",
            ) from exc

        try:
            self._broker.place_order(account_hash=account_hash, order_payload=order_payload)
        except Exception as exc:
            self._audit.append(
                {
                    **audit_event,
                    "status": "failed",
                    "reason": "placement_error",
                    "error": str(exc),
                    "risk_check": risk_result.model_dump(mode="json"),
                    "preview_response": preview,
                }
            )
            raise ProposalExecutionError(
                status_code=502,
                detail=f"Order failed: {exc}",
            ) from exc

        self._audit.append(
            {
                **audit_event,
                "status": "executed",
                "risk_check": risk_result.model_dump(mode="json"),
                "preview_response": preview,
            }
        )
        return {
            "status": "executed",
            "symbol": proposal["symbol"],
            "action": proposal["action"],
            "quantity": proposal["quantity"],
            "order_type": proposal.get("order_type", "MARKET"),
            "limit_price": proposal.get("limit_price"),
            "risk_check": risk_result.model_dump(mode="json"),
            "preview_response": preview,
        }


def build_order_payload(proposal: dict) -> dict:
    """Build Schwab order payload from a proposal dict.

    Default to LIMIT orders so they can be submitted at any time (including
    after hours) and queue for execution when the market opens.  A MARKET
    order on a CASH account is rejected outside regular market hours.
    """
    order_type = proposal.get("order_type", "LIMIT")
    limit_price = proposal.get("limit_price")

    # If caller requested MARKET but we have no after-hours support, keep it —
    # but the agent should always supply a limit_price via get_quotes first.
    if order_type == "LIMIT" and limit_price is None:
        # Fallback: treat as MARKET (will fail after hours, but safe fallback)
        order_type = "MARKET"

    payload: dict = {
        "orderType": order_type,
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": proposal["action"],
                "quantity": proposal["quantity"],
                "instrument": {"symbol": proposal["symbol"], "assetType": "EQUITY"},
            }
        ],
    }
    if order_type == "LIMIT" and limit_price is not None:
        payload["price"] = f"{float(limit_price):.2f}"
    return payload


def _build_order_intent(broker_service: SchwabBrokerService, proposal: dict) -> OrderIntent:
    reference_price = proposal.get("limit_price")
    if reference_price is None:
        quotes = broker_service.get_quotes([proposal["symbol"]])
        quote = quotes.get(proposal["symbol"], {}).get("quote", {})
        reference_price = (
            quote.get("lastPrice")
            or quote.get("mark")
            or quote.get("askPrice")
            or quote.get("bidPrice")
        )
    if reference_price is None:
        raise ProposalExecutionError(
            status_code=502,
            detail="Unable to determine a reference price for risk checks.",
        )

    try:
        action = TradeAction(str(proposal["action"]).lower())
        order_type = OrderType(str(proposal.get("order_type", "MARKET")).lower())
    except ValueError as exc:
        raise ProposalExecutionError(
            status_code=422,
            detail=f"Unsupported proposal shape: {exc}",
        ) from exc

    return OrderIntent(
        symbol=str(proposal["symbol"]),
        action=action,
        order_type=order_type,
        quantity=float(proposal["quantity"]),
        reference_price=float(reference_price),
        limit_price=_optional_float(proposal.get("limit_price")),
        stop_price=_optional_float(proposal.get("stop_price")),
    )


def _build_account_snapshot(account_payload: dict) -> AccountSnapshot:
    account = account_payload.get("securitiesAccount", account_payload)
    balances = account.get("currentBalances") or account.get("initialBalances") or {}
    equity = float(balances.get("liquidationValue") or 0)
    if equity <= 0:
        raise ProposalExecutionError(
            status_code=502,
            detail="Unable to determine account equity for risk checks.",
        )

    cash = float(
        balances.get("cashAvailableForTrading")
        or balances.get("cashBalance")
        or balances.get("cashEquivalents")
        or 0
    )
    positions: list[PositionSnapshot] = []
    for raw in account.get("positions", []):
        instrument = raw.get("instrument") or {}
        symbol = instrument.get("symbol")
        long_quantity = float(raw.get("longQuantity") or 0)
        short_quantity = float(raw.get("shortQuantity") or 0)
        if not symbol or (long_quantity == 0 and short_quantity == 0):
            continue
        quantity = long_quantity if long_quantity > 0 else short_quantity
        side = TradeAction.BUY if long_quantity > 0 else TradeAction.SELL
        positions.append(
            PositionSnapshot(
                symbol=str(symbol),
                quantity=abs(quantity),
                market_value=float(raw.get("marketValue") or 0),
                side=side,
            )
        )

    return AccountSnapshot(
        equity=equity,
        cash=cash,
        realized_pnl_today=float(balances.get("currentDayProfitLoss") or 0),
        open_positions=positions,
    )


def _build_risk_policy(settings: Any, proposal: dict) -> RiskPolicy:
    max_order_notional = getattr(settings, "live_order_max_order_notional_dollars", None)
    if max_order_notional is None and str(proposal.get("action", "")).upper() == "BUY":
        max_order_notional = getattr(settings, "buy_scan_budget", None)

    max_symbol_allocation = getattr(settings, "live_order_max_symbol_allocation_pct", None)
    if max_symbol_allocation is None:
        concentration_pct = getattr(settings, "alert_concentration_pct", None)
        if concentration_pct is not None:
            max_symbol_allocation = concentration_pct / 100

    return RiskPolicy(
        max_daily_loss_dollars=getattr(settings, "live_order_max_daily_loss_dollars", None),
        max_open_positions=getattr(settings, "live_order_max_open_positions", None),
        max_order_notional_dollars=max_order_notional,
        max_single_trade_risk_dollars=getattr(
            settings, "live_order_max_single_trade_risk_dollars", None
        ),
        max_symbol_allocation_pct=max_symbol_allocation,
        require_stop_loss_for_entries=getattr(
            settings, "live_order_require_stop_loss_for_entries", False
        ),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
