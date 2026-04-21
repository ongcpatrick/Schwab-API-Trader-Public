"""Schwab WebSocket quote streaming — live price cache for the dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

# LEVELONE_EQUITIES field IDs (verified against live Schwab data)
# 1=bid, 2=ask, 3=last, 8=volume, 12=closePrice, 18=netChange($), 29=openPrice, 31=netPctChange
_QUOTE_SERVICE = "LEVELONE_EQUITIES"
_QUOTE_FIELDS = "0,1,2,3,8,12,18,29,31"


class QuoteStreamService:
    """Maintains a live quote cache via the Schwab WebSocket streaming API.

    Runs in a background daemon thread with its own asyncio event loop so it
    doesn't block the FastAPI server.  The cache is thread-safe via a lock;
    readers (SSE endpoint) call get_quotes() without blocking writers.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        *,
        access_token: str,
        streamer_url: str,
        customer_id: str,
        correl_id: str,
        channel: str,
        func_id: str,
        symbols: list[str],
    ) -> None:
        """Start the streaming background thread.  No-op if already running."""
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            kwargs=dict(
                access_token=access_token,
                streamer_url=streamer_url,
                customer_id=customer_id,
                correl_id=correl_id,
                channel=channel,
                func_id=func_id,
                symbols=symbols,
            ),
            daemon=True,
            name="quote-streamer",
        )
        self._thread.start()
        logger.info(
            "Quote stream starting for %d symbol(s): %s",
            len(symbols),
            ", ".join(symbols),
        )

    def stop(self) -> None:
        """Signal the background thread to exit cleanly."""
        self._stop.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    def get_quotes(self) -> dict[str, dict]:
        """Return a snapshot of the current quote cache (symbol → fields)."""
        with self._lock:
            return dict(self._quotes)

    # ── internals ─────────────────────────────────────────────────────────

    def _set_quote(self, symbol: str, fields: dict) -> None:
        with self._lock:
            existing = dict(self._quotes.get(symbol, {}))
            existing.update(fields)
            existing["symbol"] = symbol
            self._quotes[symbol] = existing

    def _run_loop(self, **kwargs: object) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._stream(**kwargs))  # type: ignore[arg-type]
        except Exception:
            logger.exception("Streaming event loop crashed")
        finally:
            self._loop.close()
            self._loop = None

    async def _stream(
        self,
        *,
        access_token: str,
        streamer_url: str,
        customer_id: str,
        correl_id: str,
        channel: str,
        func_id: str,
        symbols: list[str],
    ) -> None:
        import ssl

        import certifi
        import websockets  # local import — only needed in background thread

        ssl_ctx = ssl.create_default_context(cafile=certifi.where())

        login_req = json.dumps({
            "requests": [{
                "service": "ADMIN",
                "requestid": "0",
                "command": "LOGIN",
                "SchwabClientCustomerId": customer_id,
                "SchwabClientCorrelId": correl_id,
                "parameters": {
                    "Authorization": access_token,
                    "SchwabClientChannel": channel,
                    "SchwabClientFunctionId": func_id,
                },
            }]
        })

        subs_req = json.dumps({
            "requests": [{
                "service": _QUOTE_SERVICE,
                "requestid": "1",
                "command": "SUBS",
                "SchwabClientCustomerId": customer_id,
                "SchwabClientCorrelId": correl_id,
                "parameters": {
                    "keys": ",".join(symbols),
                    "fields": _QUOTE_FIELDS,
                },
            }]
        })

        while not self._stop.is_set():
            try:
                async with websockets.connect(streamer_url, ssl=ssl_ctx, open_timeout=15) as ws:
                    # Authenticate
                    await ws.send(login_req)
                    raw_resp = await asyncio.wait_for(ws.recv(), timeout=10)
                    resp = json.loads(raw_resp)
                    code = (
                        resp.get("response", [{}])[0]
                        .get("content", {})
                        .get("code", -1)
                    )
                    if code != 0:
                        logger.error(
                            "Schwab stream login rejected (code=%s): %s", code, resp
                        )
                        return

                    logger.info(
                        "Stream authenticated. Subscribing %s for %d symbols.",
                        _QUOTE_SERVICE, len(symbols),
                    )
                    await ws.send(subs_req)

                    async for raw in ws:
                        if self._stop.is_set():
                            return
                        try:
                            self._handle(json.loads(raw))
                        except Exception:
                            logger.debug("Stream message parse error", exc_info=True)

            except Exception:
                if self._stop.is_set():
                    return
                logger.warning("Stream disconnected, reconnecting in 5s...", exc_info=True)
                await asyncio.sleep(5)

    def _handle(self, msg: dict) -> None:
        """Parse a LEVELONE_EQUITIES data message and merge into cache."""
        for chunk in msg.get("data", []):
            if chunk.get("service") != _QUOTE_SERVICE:
                continue
            for entry in chunk.get("content", []):
                sym = entry.get("key")
                if not sym:
                    continue
                fields: dict = {"ts": time.time()}

                # Helper — JSON keys are strings after parsing
                def _get(fid: int):
                    return entry.get(str(fid))

                # LEVELONE_EQUITIES verified field IDs
                if _get(1) is not None:
                    fields["bid"] = _get(1)
                if _get(2) is not None:
                    fields["ask"] = _get(2)
                if _get(3) is not None:
                    fields["last"] = _get(3)
                if _get(8) is not None:
                    fields["volume"] = _get(8)
                if _get(12) is not None:
                    fields["prevClose"] = _get(12)   # previous day close price
                if _get(18) is not None:
                    fields["netChange"] = _get(18)   # net change in dollars
                if _get(29) is not None:
                    fields["openPrice"] = _get(29)   # today's open price
                if _get(31) is not None:
                    fields["netPctChange"] = _get(31)  # net percent change

                if fields:
                    self._set_quote(sym, fields)


# Module-level singleton — imported by route handlers
stream_service = QuoteStreamService()
