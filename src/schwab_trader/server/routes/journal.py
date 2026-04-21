"""Trade journal routes."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.journal.metrics import evaluate_completed_trades
from schwab_trader.journal.models import (
    CompletedTrade,
    CompletedTradeRebuildSummary,
    JournalOverview,
    StoredCompletedTrade,
    SyncRunSummary,
    TradeEvaluationSummary,
    TradeScorecard,
)
from schwab_trader.journal.reconstruction import (
    CompletedTradeRebuilder,
    TradeScorecardService,
)
from schwab_trader.journal.store import SQLiteJournalStore
from schwab_trader.journal.sync import JournalSyncService
from schwab_trader.server.dependencies import get_broker_service, get_journal_store


class TradeEvaluationRequest(BaseModel):
    """Request payload for trade evaluation."""

    trades: list[CompletedTrade]


router = APIRouter()


def _parse_http_error(exc: httpx.HTTPStatusError) -> object:
    try:
        return exc.response.json()
    except ValueError:
        return exc.response.text or "Schwab request failed."


def _execute_journal_call(operation):
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


@router.post("/evaluate", response_model=TradeEvaluationSummary)
def evaluate_trades(payload: TradeEvaluationRequest) -> TradeEvaluationSummary:
    """Evaluate completed trades and return summary statistics."""

    return evaluate_completed_trades(payload.trades)


@router.get("/overview", response_model=JournalOverview)
def journal_overview(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
) -> JournalOverview:
    """Return local journal counts and latest sync metadata."""

    return store.get_overview()


@router.get("/accounts")
def journal_accounts(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
) -> list[dict[str, object]]:
    """Return locally stored account snapshots."""

    return store.list_accounts()


@router.get("/orders")
def journal_orders(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    account_hash: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """Return locally stored order snapshots."""

    return store.list_orders(account_hash=account_hash, limit=limit)


@router.get("/transactions")
def journal_transactions(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    account_hash: Annotated[str | None, Query()] = None,
    transaction_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """Return locally stored transaction snapshots."""

    return store.list_transactions(
        account_hash=account_hash,
        transaction_type=transaction_type,
        limit=limit,
    )


@router.get("/sync-runs", response_model=list[SyncRunSummary])
def journal_sync_runs(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SyncRunSummary]:
    """Return recent local sync runs."""

    return store.list_sync_runs(limit=limit)


@router.post("/rebuild-completed-trades", response_model=CompletedTradeRebuildSummary)
def rebuild_completed_trades(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
) -> CompletedTradeRebuildSummary:
    """Reconstruct normalized completed trades from raw orders and transactions."""

    return CompletedTradeRebuilder(store=store).rebuild()


@router.get("/completed-trades", response_model=list[StoredCompletedTrade])
def journal_completed_trades(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    account_hash: Annotated[str | None, Query()] = None,
    symbol: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[StoredCompletedTrade]:
    """Return reconstructed completed trades."""

    return [
        StoredCompletedTrade.model_validate(item)
        for item in store.list_completed_trades(
            account_hash=account_hash,
            symbol=symbol,
            limit=limit,
        )
    ]


@router.get("/scorecard", response_model=TradeScorecard)
def journal_scorecard(
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    account_hash: Annotated[str | None, Query()] = None,
    symbol: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> TradeScorecard:
    """Return a scorecard over reconstructed completed trades."""

    return TradeScorecardService(store=store).build_scorecard(
        account_hash=account_hash,
        symbol=symbol,
        limit=limit,
    )


@router.post("/sync", response_model=SyncRunSummary)
def sync_journal(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    store: Annotated[SQLiteJournalStore, Depends(get_journal_store)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SyncRunSummary:
    """Run a local journal sync over the trailing day window."""

    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    service = JournalSyncService(broker_service=broker_service, store=store)
    return _execute_journal_call(
        lambda: service.sync(
            orders_from=start,
            orders_to=now,
            transactions_from=start,
            transactions_to=now,
        )
    )


@router.get("/dashboard", response_class=HTMLResponse)
def journal_dashboard() -> HTMLResponse:
    """Serve a lightweight local dashboard for journal inspection."""

    return HTMLResponse(_dashboard_html())


def _dashboard_html() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Local Journal Dashboard</title>
    <style>
      :root {
        --bg: #f7f4ee;
        --panel: rgba(255, 255, 255, 0.84);
        --ink: #1f1a17;
        --muted: #6b625b;
        --line: rgba(31, 26, 23, 0.12);
        --accent: #0f766e;
        --accent-soft: rgba(15, 118, 110, 0.14);
        --shadow: 0 24px 64px rgba(31, 26, 23, 0.08);
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family:
          ui-sans-serif,
          system-ui,
          -apple-system,
          BlinkMacSystemFont,
          "Segoe UI",
          sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 28%),
          linear-gradient(180deg, #fbfaf6 0%, var(--bg) 100%);
      }

      main {
        max-width: 1200px;
        margin: 0 auto;
        padding: 32px 20px 64px;
      }

      .hero {
        display: grid;
        gap: 12px;
        margin-bottom: 24px;
      }

      h1 {
        margin: 0;
        font-size: clamp(2rem, 4vw, 3.25rem);
        line-height: 0.95;
        letter-spacing: -0.04em;
      }

      .subtle {
        color: var(--muted);
        max-width: 720px;
        line-height: 1.5;
      }

      .cards {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        margin: 24px 0 28px;
      }

      .card, .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 20px;
        box-shadow: var(--shadow);
        backdrop-filter: blur(10px);
      }

      .card {
        padding: 18px 18px 16px;
      }

      .eyebrow {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        margin-bottom: 8px;
      }

      .metric {
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.04em;
      }

      .grid {
        display: grid;
        gap: 14px;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      }

      .panel {
        padding: 18px;
      }

      .panel h2 {
        margin: 0 0 14px;
        font-size: 1.05rem;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.94rem;
      }

      th, td {
        text-align: left;
        padding: 10px 0;
        border-bottom: 1px solid var(--line);
        vertical-align: top;
      }

      th {
        color: var(--muted);
        font-weight: 600;
      }

      .pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border-radius: 999px;
        padding: 6px 10px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 0.82rem;
        font-weight: 600;
      }

      .empty {
        color: var(--muted);
        padding: 8px 0 2px;
      }

      @media (max-width: 720px) {
        main { padding: 24px 14px 48px; }
        .panel { overflow-x: auto; }
      }
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <div class="pill">Local Journal Dashboard</div>
        <h1>Inspect your synced Schwab journal without opening SQLite.</h1>
        <p class="subtle">
          This view reads the local journal API endpoints and shows the latest sync snapshot,
          stored accounts, recent orders, recent transactions, and recent sync runs.
        </p>
      </section>

      <section class="cards">
        <article class="card">
          <div class="eyebrow">Accounts</div>
          <div class="metric" id="account-count">-</div>
        </article>
        <article class="card">
          <div class="eyebrow">Orders</div>
          <div class="metric" id="order-count">-</div>
        </article>
        <article class="card">
          <div class="eyebrow">Transactions</div>
          <div class="metric" id="transaction-count">-</div>
        </article>
        <article class="card">
          <div class="eyebrow">Last Sync</div>
          <div class="metric" id="last-sync-status">-</div>
        </article>
      </section>

      <section class="grid">
        <article class="panel">
          <h2>Accounts</h2>
          <div id="accounts"></div>
        </article>
        <article class="panel">
          <h2>Recent Sync Runs</h2>
          <div id="sync-runs"></div>
        </article>
        <article class="panel">
          <h2>Recent Orders</h2>
          <div id="orders"></div>
        </article>
        <article class="panel">
          <h2>Recent Transactions</h2>
          <div id="transactions"></div>
        </article>
      </section>
    </main>

    <script>
      async function loadJson(path) {
        const response = await fetch(path);
        if (!response.ok) {
          throw new Error(`Request failed: ${path}`);
        }
        return response.json();
      }

      function table(headers, rows) {
        if (!rows.length) {
          return '<div class="empty">No local data yet.</div>';
        }
        const head = headers.map((header) => `<th>${header}</th>`).join('');
        const body = rows
          .map((row) => {
            const cells = row.map((cell) => `<td>${cell ?? ''}</td>`).join('');
            return `<tr>${cells}</tr>`;
          })
          .join('');
        return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
      }

      function fmtDate(value) {
        if (!value) return '-';
        return new Date(value).toLocaleString();
      }

      async function hydrate() {
        const [overview, accounts, orders, transactions, syncRuns] = await Promise.all([
          loadJson('/api/v1/journal/overview'),
          loadJson('/api/v1/journal/accounts'),
          loadJson('/api/v1/journal/orders?limit=8'),
          loadJson('/api/v1/journal/transactions?limit=8'),
          loadJson('/api/v1/journal/sync-runs?limit=8'),
        ]);

        document.getElementById('account-count').textContent = overview.account_count;
        document.getElementById('order-count').textContent = overview.order_count;
        document.getElementById('transaction-count').textContent = overview.transaction_count;
        document.getElementById('last-sync-status').textContent =
          overview.last_sync?.status ?? 'none';

        document.getElementById('accounts').innerHTML = table(
          ['Account', 'Synced'],
          accounts.map((item) => [item.masked_account_number, fmtDate(item.synced_at)]),
        );
        document.getElementById('orders').innerHTML = table(
          ['Account', 'Order', 'Status', 'Entered'],
          orders.map((item) => [
            item.account_hash,
            item.order_id,
            item.status,
            fmtDate(item.entered_time),
          ]),
        );
        document.getElementById('transactions').innerHTML = table(
          ['Account', 'Txn', 'Type', 'Symbol', 'Date'],
          transactions.map((item) => [
            item.account_hash,
            item.transaction_id,
            item.transaction_type,
            item.symbol,
            fmtDate(item.trade_date),
          ]),
        );
        document.getElementById('sync-runs').innerHTML = table(
          ['Status', 'Accounts', 'Orders', 'Transactions', 'Completed'],
          syncRuns.map((item) => [
            item.status,
            item.accounts_synced,
            item.orders_synced,
            item.transactions_synced,
            fmtDate(item.completed_at),
          ]),
        );
      }

      hydrate().catch((error) => {
        const toast =
          '<div style="position:fixed;bottom:16px;right:16px;background:#fff;' +
          'border:1px solid rgba(0,0,0,.12);padding:12px 14px;border-radius:12px;">' +
          `${error.message}</div>`;
        document.body.insertAdjacentHTML(
          'beforeend',
          toast,
        );
      });
    </script>
  </body>
</html>
"""
