"""Portfolio performance history routes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.core.settings import get_settings
from schwab_trader.performance.service import PerformanceService
from schwab_trader.performance.store import PerformanceStore
from schwab_trader.server.dependencies import get_broker_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level singleton — same db directory as the journal
_store = PerformanceStore(str(Path(".data/performance.db")))
_service = PerformanceService(_store)


def get_performance_service() -> PerformanceService:
    return _service


@router.get("/history")
def performance_history(days: int = 90) -> dict:
    """Return portfolio snapshot series + computed metrics for charting.

    Query param ``days`` controls how far back to look (default 90).
    """
    days = max(7, min(days, 1825))  # clamp 7 d – 5 yr
    return _service.get_history(days=days)


@router.post("/snapshot")
def take_snapshot(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Manually trigger a portfolio snapshot (also runs automatically via scheduler)."""
    result = _service.take_snapshot(broker_service)
    if result:
        return {"status": "saved", "snapshot": result}
    return {"status": "failed", "detail": "Could not retrieve portfolio value"}


@router.post("/backfill")
def backfill_history(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    days: int = 365,
) -> dict:
    """Estimate historical portfolio values using current holdings × past closes.

    Only fills dates with no existing snapshot. Values assume no trades occurred.
    """
    inserted = _service.backfill(broker_service, days=days)
    return {"status": "ok", "inserted": inserted}


@router.post("/rebuild")
def rebuild_full_history(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    years: int = 10,
) -> dict:
    """Reconstruct ALL-TIME portfolio history from actual Schwab transaction data.

    Fetches up to ``years`` years of TRADE transactions, walks backward from
    today's holdings to determine what you actually owned on each historical date,
    then prices each day with yfinance closes. Falls back to the current-holdings
    estimate when no transaction data is available.

    This is the authoritative rebuild — run it once after syncing your journal.
    """
    years = max(1, min(years, 20))
    result = _service.rebuild_full_history(broker_service, years=years)
    return {"status": "ok", **result}
