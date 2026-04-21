"""Schwab read-only, preview, and live-streaming routes."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from typing import Annotated

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.server.dependencies import get_broker_service
from schwab_trader.streaming.service import stream_service

router = APIRouter()


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_http_error(exc: httpx.HTTPStatusError) -> object:
    try:
        return exc.response.json()
    except ValueError:
        return exc.response.text or "Schwab request failed."


def _execute_broker_call(operation: Callable[[], object]) -> object:
    try:
        return operation()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=_parse_http_error(exc),
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Schwab API unreachable: {exc}",
        ) from exc


@router.get("/accounts/account-numbers")
def account_numbers(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> object:
    return _execute_broker_call(broker_service.get_account_numbers)


@router.get("/accounts")
def accounts(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    fields: Annotated[str | None, Query()] = None,
) -> object:
    return _execute_broker_call(lambda: broker_service.get_accounts(fields=_split_csv(fields)))


@router.get("/accounts/{account_hash}")
def account(
    account_hash: str,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    fields: Annotated[str | None, Query()] = None,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_account(account_hash, fields=_split_csv(fields))
    )


@router.get("/accounts/{account_hash}/orders")
def account_orders(
    account_hash: str,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    fromEnteredTime: str,
    toEnteredTime: str,
    maxResults: int | None = None,
    status: str | None = None,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_orders_for_account(
            account_hash=account_hash,
            from_entered_time=fromEnteredTime,
            to_entered_time=toEnteredTime,
            max_results=maxResults,
            status=status,
        )
    )


@router.get("/orders")
def all_orders(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    fromEnteredTime: str,
    toEnteredTime: str,
    maxResults: int | None = None,
    status: str | None = None,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_all_orders(
            from_entered_time=fromEnteredTime,
            to_entered_time=toEnteredTime,
            max_results=maxResults,
            status=status,
        )
    )


@router.get("/accounts/{account_hash}/transactions")
def transactions(
    account_hash: str,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    startDate: str,
    endDate: str,
    types: str,
    symbol: str | None = None,
) -> object:
    type_list: Sequence[str] = [item.strip() for item in types.split(",") if item.strip()]
    return _execute_broker_call(
        lambda: broker_service.get_transactions(
            account_hash=account_hash,
            start_date=startDate,
            end_date=endDate,
            types=type_list,
            symbol=symbol,
        )
    )


@router.get("/accounts/{account_hash}/transactions/{transaction_id}")
def transaction(
    account_hash: str,
    transaction_id: int,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_transaction(account_hash, transaction_id)
    )


@router.get("/user-preferences")
def user_preferences(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> object:
    return _execute_broker_call(broker_service.get_user_preferences)


@router.get("/quotes")
def quotes(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    symbols: str,
    fields: Annotated[str | None, Query()] = None,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_quotes(
            [item.strip() for item in symbols.split(",") if item.strip()],
            fields=_split_csv(fields),
        )
    )


@router.get("/market-hours")
def market_hours(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    markets: str,
    date: str | None = None,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_market_hours(
            [item.strip() for item in markets.split(",") if item.strip()],
            date=date,
        )
    )


@router.get("/pricehistory")
def price_history(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    symbol: str,
    periodType: str = "month",
    period: int = 1,
    frequencyType: str = "daily",
    frequency: int = 1,
) -> object:
    return _execute_broker_call(
        lambda: broker_service.get_price_history(
            symbol.upper(),
            period_type=periodType,
            period=period,
            frequency_type=frequencyType,
            frequency=frequency,
        )
    )


@router.get("/options-chain")
def options_chain(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    symbol: str,
    contractType: str = "ALL",
    strikeCount: int = 10,
) -> dict:
    """Return the options chain for a symbol."""
    return _execute_broker_call(
        lambda: broker_service.get_options_chain(
            symbol,
            contract_type=contractType,
            strike_count=strikeCount,
        )
    )


@router.post("/accounts/{account_hash}/preview-order")
def preview_order(
    account_hash: str,
    order_payload: Annotated[dict, Body()],
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> object:
    return _execute_broker_call(
        lambda: broker_service.preview_order(account_hash=account_hash, order_payload=order_payload)
    )


# ── Live quote streaming ──────────────────────────────────────────────────────

@router.post("/stream/start")
def start_quote_stream(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Start the background WebSocket quote stream for all held positions.

    Safe to call repeatedly — no-op when already running.
    """
    if stream_service.is_running:
        return {"status": "already_running"}

    # Fetch streamer credentials
    prefs = _execute_broker_call(broker_service.get_user_preferences)
    streamer_info = prefs.get("streamerInfo", [{}])[0]
    streamer_url = streamer_info.get("streamerSocketUrl", "")
    customer_id = streamer_info.get("schwabClientCustomerId", "")
    correl_id = streamer_info.get("schwabClientCorrelId", "")
    channel = streamer_info.get("schwabClientChannel", "N9")
    func_id = streamer_info.get("schwabClientFunctionId", "APIAPP")

    if not streamer_url:
        raise HTTPException(status_code=503, detail="Streamer URL not available in user preferences")

    # Collect symbols from current positions
    accounts = _execute_broker_call(lambda: broker_service.get_accounts(fields=["positions"]))
    symbols: list[str] = []
    for acct in (accounts or []):
        for pos in acct.get("securitiesAccount", {}).get("positions", []):
            sym = pos.get("instrument", {}).get("symbol")
            if sym and sym not in symbols:
                symbols.append(sym)

    if not symbols:
        return {"status": "no_positions", "detail": "No positions found to stream"}

    access_token = broker_service.get_access_token()

    stream_service.start(
        access_token=access_token,
        streamer_url=streamer_url,
        customer_id=customer_id,
        correl_id=correl_id,
        channel=channel,
        func_id=func_id,
        symbols=symbols,
    )
    return {"status": "started", "symbols": symbols}


@router.get("/stream")
async def quote_stream_sse() -> StreamingResponse:
    """SSE endpoint — pushes quote updates to the dashboard every ~250 ms.

    Sends the full quote cache on every change, plus a heartbeat comment
    every 30 s to keep the connection alive.
    """
    async def event_gen():
        prev_json = ""
        last_heartbeat = time.monotonic()
        while True:
            quotes = stream_service.get_quotes()
            as_json = json.dumps(quotes)
            if as_json != prev_json:
                yield f"data: {as_json}\n\n"
                prev_json = as_json
            elif time.monotonic() - last_heartbeat > 30:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/status")
def stream_status() -> dict:
    """Return whether the quote stream is currently connected."""
    quotes = stream_service.get_quotes()
    return {
        "running": stream_service.is_running,
        "symbols": sorted(quotes.keys()),
        "quote_count": len(quotes),
    }


@router.get("/stream/quotes")
def stream_quotes() -> dict:
    """Return the current quote cache snapshot (for debugging)."""
    return stream_service.get_quotes()
