"""Application factory for the local control plane."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Module-level limiter — imported by route files that need per-endpoint rate limits
limiter = Limiter(key_func=get_remote_address)

from schwab_trader.core.settings import get_settings
from schwab_trader.server.routes.auth import router as auth_router
from schwab_trader.server.routes.health import router as health_router
from schwab_trader.server.routes.home import router as home_router
from schwab_trader.server.routes.journal import router as journal_router
from schwab_trader.server.routes.risk import router as risk_router
from schwab_trader.server.routes.advisor import router as advisor_router
from schwab_trader.server.routes.earnings import router as earnings_router
from schwab_trader.server.routes.schwab import router as schwab_router
from schwab_trader.server.routes.agent import router as agent_router, trade_router
from schwab_trader.server.routes.performance import router as performance_router
from schwab_trader.server.routes.news import router as news_router
from schwab_trader.streaming.service import stream_service

logger = logging.getLogger(__name__)

_stop_event = threading.Event()


def _scheduler_loop(interval_seconds: int) -> None:
    """Background thread: run agent check + buy scan + daily performance snapshot."""
    import time as _time
    from schwab_trader.server.routes.agent import run_scheduled_check, run_scheduled_buy_scan, run_scheduled_sell_scan, _agent, _store
    from schwab_trader.thesis import service as _thesis
    from schwab_trader.server.routes.performance import _service as perf_service
    from schwab_trader.server.dependencies import get_broker_service as _gbk

    logger.info("Scheduler started (interval: %ds)", interval_seconds)
    if _stop_event.wait(timeout=30):
        return

    _last_snapshot_date: str = ""
    _last_buy_scan_ts: float = 0.0
    _last_sell_scan_ts: float = 0.0
    _last_thesis_check_ts: float = 0.0

    while not _stop_event.wait(timeout=interval_seconds):
        settings = get_settings()

        # ── agent portfolio check ─────────────────────────────────────
        logger.info("Running scheduled agent check...")
        try:
            result = run_scheduled_check()
            if result:
                logger.info("Agent check raised %d flag(s)", len(result.get("flags", [])))
        except Exception:
            logger.exception("Scheduler: agent check error")

        # ── exit target monitoring ────────────────────────────────────
        try:
            broker = _gbk()
            triggered = _agent.check_exit_targets(broker)
            if triggered:
                logger.info("Exit targets triggered for %d symbol(s)", len(triggered))
                # Surface as a portfolio scan alert
                import uuid as _uuid
                from datetime import datetime as _dt
                from schwab_trader.agent.monitor import Flag as _Flag
                flags = [
                    _Flag(
                        type="EXIT_TARGET",
                        symbol=t["symbol"],
                        severity="HIGH" if t["kind"] == "stop" else "MEDIUM",
                        description=t["description"],
                        proposed_action=f"Review and consider selling {t['symbol']}.",
                    )
                    for t in triggered
                ]
                exit_alert = {
                    "id": str(_uuid.uuid4()),
                    "timestamp": _dt.now().isoformat(),
                    "alert_type": "EXIT_TARGET",
                    "flags": [f.to_dict() for f in flags],
                    "claude_analysis": None,
                    "proposals": [],
                    "portfolio_value": 0,
                    "status": "pending",
                }
                _store.save_alert(exit_alert)
        except Exception:
            logger.exception("Scheduler: exit target check error")

        # ── buy scan (cadence controlled by buy_scan_interval_hours) ──
        buy_interval = settings.buy_scan_interval_hours * 3600
        if _time.time() - _last_buy_scan_ts >= buy_interval:
            logger.info("Running scheduled buy scan...")
            try:
                result = run_scheduled_buy_scan()
                if result:
                    logger.info("Buy scan produced %d proposal(s)", len(result.get("proposals", [])))
                _last_buy_scan_ts = _time.time()
            except Exception:
                logger.exception("Scheduler: buy scan error")

        # ── sell scan (weekly cadence — every 7 days) ────────────────
        sell_interval = 7 * 24 * 3600
        if _time.time() - _last_sell_scan_ts >= sell_interval:
            logger.info("Running scheduled sell scan...")
            try:
                result = run_scheduled_sell_scan()
                if result:
                    logger.info("Sell scan produced %d proposal(s)", len(result.get("proposals", [])))
                _last_sell_scan_ts = _time.time()
            except Exception:
                logger.exception("Scheduler: sell scan error")

        # ── thesis check (weekly cadence — every 7 days) ─────────────
        thesis_interval = 7 * 24 * 3600
        if _time.time() - _last_thesis_check_ts >= thesis_interval:
            logger.info("Running weekly thesis check...")
            try:
                from schwab_trader.advisor.service import AdvisorService
                broker = _gbk()
                advisor = AdvisorService(broker, settings.anthropic_api_key)
                _thesis.seed_from_alerts(_store)
                updated = _thesis.check_all(broker, advisor)
                logger.info("Thesis check complete: %d position(s) reviewed", len(updated))
                _last_thesis_check_ts = _time.time()
            except Exception:
                logger.exception("Scheduler: thesis check error")

        # ── daily performance snapshot ────────────────────────────────
        from datetime import date as _date
        today = _date.today().isoformat()
        if today != _last_snapshot_date:
            try:
                broker = _gbk()
                snap = perf_service.take_snapshot(broker)
                if snap:
                    _last_snapshot_date = today
                    logger.info(
                        "Performance snapshot: $%,.2f on %s",
                        snap["portfolio_value"],
                        today,
                    )
            except Exception:
                logger.exception("Scheduler: performance snapshot error")


def _bootstrap_token_from_env() -> None:
    """On Railway/cloud: write SCHWAB_TOKEN_JSON env var to the token file.

    Set SCHWAB_TOKEN_JSON to the full contents of your local
    .data/schwab-token.json before deploying.  The server writes it to disk
    at startup so the OAuth client can load it normally.
    """
    import json
    import os

    token_json = os.environ.get("SCHWAB_TOKEN_JSON", "").strip()
    if not token_json:
        return

    settings = get_settings()
    token_path = settings.schwab_token_path
    try:
        # Validate it's parseable before writing
        json.loads(token_json)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token_json, encoding="utf-8")
        try:
            import os as _os
            _os.chmod(token_path, 0o600)
        except PermissionError:
            pass
        logger.info("Token written from SCHWAB_TOKEN_JSON env var → %s", token_path)
    except Exception:
        logger.exception("Failed to write token from SCHWAB_TOKEN_JSON")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_token_from_env()
    settings = get_settings()
    interval = max(settings.agent_check_interval_minutes, 5) * 60
    _stop_event.clear()
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(interval,),
        daemon=True,
        name="agent-scheduler",
    )
    thread.start()
    logger.info("Scheduler thread started")

    # Take an immediate snapshot on startup (best-effort)
    def _startup_snapshot() -> None:
        import time as _time
        _time.sleep(5)  # let server fully start
        try:
            from schwab_trader.server.routes.performance import _service as perf_service, _store as perf_store
            from schwab_trader.server.dependencies import get_broker_service as _gbk
            broker = _gbk()
            # Always take today's snapshot
            perf_service.take_snapshot(broker)
            # Backfill 90 days of estimated history if this is a fresh database
            if perf_store.count() <= 1:
                logger.info("Fresh performance DB — backfilling 90 days of estimated history")
                inserted = perf_service.backfill(broker, days=90)
                logger.info("Backfill complete: %d dates inserted", inserted)
        except Exception:
            logger.exception("Startup snapshot/backfill error")

    threading.Thread(target=_startup_snapshot, daemon=True, name="startup-snapshot").start()

    yield
    _stop_event.set()
    stream_service.stop()
    logger.info("Scheduler and quote stream stopped")


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(home_router)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(journal_router, prefix="/api/v1/journal", tags=["journal"])
app.include_router(risk_router, prefix="/api/v1/risk", tags=["risk"])
app.include_router(schwab_router, prefix="/api/v1/schwab", tags=["schwab"])
app.include_router(advisor_router, prefix="/api/v1/advisor", tags=["advisor"])
app.include_router(earnings_router, prefix="/api/v1/earnings", tags=["earnings"])
app.include_router(agent_router, prefix="/api/v1/agent", tags=["agent"])
app.include_router(trade_router)  # /trade/approve/{token} and /trade/deny/{token}
app.include_router(performance_router, prefix="/api/v1/performance", tags=["performance"])
app.include_router(news_router, prefix="/api/v1/news", tags=["news"])
