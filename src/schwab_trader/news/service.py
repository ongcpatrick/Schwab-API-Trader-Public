"""News feed service — fetches headlines via yfinance and triages with Claude."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import yfinance as yf
from anthropic import Anthropic

logger = logging.getLogger(__name__)

_client = Anthropic()


def _parse_item(sym: str, item: dict) -> dict | None:
    """Normalise a yfinance news item regardless of API version.

    yfinance ≥0.2.50 wraps everything inside item["content"]; older versions
    had flat keys (title, publisher, link, providerPublishTime).
    """
    # New nested structure (yfinance ≥0.2.50)
    content = item.get("content") or {}
    if content:
        title = content.get("title", "").strip()
        publisher = (content.get("provider") or {}).get("displayName", "")
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")
        pub_str = content.get("pubDate") or content.get("displayTime") or ""
        pub_ts = 0
        published_str = ""
        if pub_str:
            try:
                dt = datetime.strptime(pub_str[:19], "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                pub_ts = int(dt.timestamp())
                published_str = dt.strftime("%b %d, %H:%M UTC")
            except Exception:
                pass
    else:
        # Legacy flat structure
        title = item.get("title", "").strip()
        publisher = item.get("publisher", "")
        link = item.get("link", "")
        pub_ts = item.get("providerPublishTime") or 0
        published_str = (
            datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%b %d, %H:%M UTC")
            if pub_ts
            else ""
        )

    if not title:
        return None

    return {
        "symbol": sym,
        "title": title,
        "publisher": publisher,
        "link": link,
        "published": pub_ts,
        "published_str": published_str,
        "material": False,
        "severity": "LOW",
        "take": "",
    }


def get_news_feed(symbols: list[str], max_per_symbol: int = 5) -> list[dict]:
    """Fetch recent news for all symbols and triage with Claude.

    Returns a flat list sorted newest-first, each item with:
    symbol, title, publisher, link, published_str, material, severity, take
    """
    all_news: list[dict] = []
    seen_titles: set[str] = set()

    for sym in symbols:
        try:
            raw_items = yf.Ticker(sym).news or []
            added = 0
            for item in raw_items:
                if added >= max_per_symbol:
                    break
                parsed = _parse_item(sym, item)
                if parsed and parsed["title"] not in seen_titles:
                    seen_titles.add(parsed["title"])
                    all_news.append(parsed)
                    added += 1
        except Exception:
            logger.debug("News fetch failed for %s", sym, exc_info=True)

    all_news.sort(key=lambda x: x["published"], reverse=True)

    if all_news:
        all_news = _triage(all_news)

    return all_news


def _triage(items: list[dict]) -> list[dict]:
    """Ask Claude Haiku to classify each headline in one batch call."""
    headlines = "\n".join(
        f"{i + 1}. [{it['symbol']}] {it['title']}"
        for i, it in enumerate(items)
    )
    try:
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    "You are a financial news analyst for a retail investor.\n"
                    "For each headline below, respond with a JSON array where each object has:\n"
                    "  index (1-based int), material (true if likely price-moving), "
                    "severity (HIGH/MEDIUM/LOW), take (≤12 word analyst take)\n\n"
                    "Headlines:\n" + headlines + "\n\n"
                    "Return ONLY a JSON array, no other text."
                ),
            }],
        )
        analyses = json.loads(msg.content[0].text)
        by_index = {int(a["index"]): a for a in analyses}
        for i, item in enumerate(items):
            a = by_index.get(i + 1, {})
            item["material"] = bool(a.get("material", False))
            item["severity"] = str(a.get("severity", "LOW")).upper()
            item["take"] = str(a.get("take", ""))
    except Exception:
        logger.debug("Claude news triage failed", exc_info=True)

    return items
