"""SEC EDGAR Form 4 service.

Fetches real corporate insider transactions (Form 4 filings) directly from EDGAR.
No API key required. EDGAR requires a User-Agent with contact email per their policy.

Flow:
  1. Map ticker -> CIK using EDGAR's company_tickers.json (cached in memory)
  2. Fetch recent submissions for each CIK
  3. Filter to Form 4 filings in the last N days
  4. Fetch and parse the Form 4 XML for transaction details
  5. Return purchases only (transaction code P), filter out sales
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import lru_cache

import certifi

logger = logging.getLogger(__name__)

_EDGAR_BASE = "https://data.sec.gov"
# EDGAR requires a real contact email in the User-Agent per their access policy.
# Replace "your@email.com" with your actual email address before running.
_HEADERS = {"User-Agent": "schwab-ai-trader your@email.com"}
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return r.read()


@lru_cache(maxsize=1)
def _load_ticker_cik_map() -> dict[str, str]:
    """Download EDGAR's full ticker->CIK mapping once and cache it."""
    try:
        data = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
        return {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in data.values()
        }
    except Exception as exc:
        logger.warning("EDGAR ticker map failed: %s", exc)
        return {}


def _get_cik(ticker: str) -> str | None:
    return _load_ticker_cik_map().get(ticker.upper())


_TX_CODE_MAP = {
    "P": "buy",   # open-market purchase
    "S": "sell",  # open-market sale
    "F": "sell",  # tax withholding (treated as sell)
    "M": "buy",   # exercise of derivative
}


def _parse_form4_xml(xml_bytes: bytes) -> list[dict]:
    """Parse Form 4 XML and return buy/sell transactions (codes P, S, F, M)."""
    trades = []
    try:
        root = ET.fromstring(xml_bytes)

        def find(el: ET.Element, tag: str) -> str:
            node = el.find(".//" + tag)
            if node is None:
                return ""
            # Direct text (e.g. transactionCode)
            if node.text and node.text.strip():
                return node.text.strip()
            # Wrapped in <value> child (e.g. transactionShares, transactionDate)
            val = node.find("value")
            return val.text.strip() if val is not None and val.text else ""

        insider_name = find(root, "rptOwnerName")
        insider_title = find(root, "officerTitle") or find(root, "rptOwnerRelationship")

        for tx in root.iter("nonDerivativeTransaction"):
            code = find(tx, "transactionCode")
            tx_type = _TX_CODE_MAP.get(code)
            if tx_type is None:
                continue
            shares_str = find(tx, "transactionShares")
            price_str = find(tx, "transactionPricePerShare")
            date_str = find(tx, "transactionDate")
            try:
                shares = float(shares_str) if shares_str else 0
                price = float(price_str) if price_str else 0
                value = int(shares * price)
            except ValueError:
                continue
            if shares <= 0:
                continue
            trades.append({
                "insider": insider_name[:80],
                "title": insider_title[:60],
                "date": date_str[:10],
                "shares": int(shares),
                "price": round(price, 2),
                "value": value,
                "transaction_type": tx_type,
                "source": "SEC EDGAR Form 4",
            })
    except Exception as exc:
        logger.debug("Form 4 XML parse error: %s", exc)
    return trades


def _fetch_insider_trades_for_symbol(ticker: str, days: int = 90) -> tuple[str, list[dict]]:
    """Fetch Form 4 purchase transactions for a single ticker from EDGAR."""
    cik = _get_cik(ticker)
    if not cik:
        return ticker, []

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_trades: list[dict] = []

    try:
        submissions = json.loads(_get(f"{_EDGAR_BASE}/submissions/CIK{cik}.json", timeout=8))
        filings = submissions.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])

        xml_fetches = 0
        for form, date, accession, doc in zip(forms, dates, accessions, primary_docs):
            if form != "4":
                continue
            if date < cutoff:
                break  # filings are sorted newest-first; stop when past cutoff
            if xml_fetches >= 5:  # cap XML fetches per symbol to limit latency
                break
            # Fetch the actual Form 4 XML
            # Strip any XSLT subdirectory prefix (e.g. "xslF345X06/filename.xml" -> "filename.xml")
            acc_clean = accession.replace("-", "")
            raw_doc = os.path.basename(doc)
            xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{raw_doc}"
            try:
                xml_bytes = _get(xml_url, timeout=6)
                xml_fetches += 1
                trades = _parse_form4_xml(xml_bytes)
                for t in trades:
                    t["ticker"] = ticker
                all_trades.extend(trades)
            except Exception as exc:
                logger.debug("Form 4 fetch %s %s: %s", ticker, accession, exc)

            if len(all_trades) >= 8:
                break

    except Exception as exc:
        logger.warning("EDGAR submissions fetch %s: %s", ticker, exc)

    return ticker, all_trades[:8]


def get_form4_trades(symbols: list[str], days: int = 90) -> dict[str, list[dict]]:
    """
    Fetch SEC EDGAR Form 4 purchase transactions for a list of symbols.
    Returns dict mapping symbol -> list of insider purchase dicts.
    """
    result: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_insider_trades_for_symbol, s, days): s for s in symbols}
        for fut in as_completed(futures):
            sym, trades = fut.result()
            result[sym] = trades
    return result
