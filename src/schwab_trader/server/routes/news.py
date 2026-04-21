"""News feed routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/feed")
def news_feed(symbols: str = "") -> list[dict]:
    """Return recent AI-triaged headlines for the given comma-separated symbols."""
    from schwab_trader.news.service import get_news_feed

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        return []
    return get_news_feed(syms)
