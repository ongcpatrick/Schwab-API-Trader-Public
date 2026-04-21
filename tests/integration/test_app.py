from fastapi.testclient import TestClient

from schwab_trader.auth.models import OAuthToken
from schwab_trader.journal.models import JournalOverview, SyncRunStatus, SyncRunSummary
from schwab_trader.server.app import app
from schwab_trader.server.dependencies import (
    get_broker_service,
    get_journal_store,
    get_oauth_service,
    get_token_store,
)

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "schwab-api-trader"}


def test_home_route_serves_html() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Schwab API Trader" in response.text


def test_trade_evaluation_endpoint_returns_summary() -> None:
    response = client.post(
        "/api/v1/journal/evaluate",
        json={
            "trades": [
                {
                    "symbol": "AAPL",
                    "side": "long",
                    "quantity": 5,
                    "entry_price": 100,
                    "exit_price": 110,
                    "fees": 1,
                    "benchmark_return_pct": 2,
                    "followed_plan": True,
                    "hold_minutes": 15,
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_trades"] == 1
    assert payload["net_pnl"] == 49.0


def test_risk_check_endpoint_returns_blocking_reasons() -> None:
    response = client.post(
        "/api/v1/risk/check-order",
        json={
            "policy": {
                "allowed_symbols": ["AAPL"],
                "max_daily_loss_dollars": 500,
                "max_open_positions": 1,
                "max_order_notional_dollars": 2000,
                "max_single_trade_risk_dollars": 100,
                "max_symbol_allocation_pct": 0.1,
                "require_stop_loss_for_entries": True,
            },
            "account": {
                "equity": 10000,
                "cash": 1000,
                "realized_pnl_today": -600,
                "open_positions": [
                    {
                        "symbol": "MSFT",
                        "quantity": 5,
                        "market_value": 1500,
                        "side": "buy",
                    }
                ],
            },
            "order": {
                "symbol": "TSLA",
                "action": "buy",
                "order_type": "market",
                "quantity": 10,
                "reference_price": 300,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is False
    assert len(payload["reasons"]) >= 3


def test_authorize_url_endpoint_uses_oauth_service() -> None:
    calls: dict[str, str] = {}

    class StubOAuthService:
        def authorization_url(
            self,
            *,
            state: str | None = None,
            code_challenge: str | None = None,
            code_challenge_method: str | None = None,
        ) -> str:
            assert state
            assert code_challenge
            assert code_challenge_method == "S256"
            calls["state"] = state
            return (
                "https://api.schwabapi.com/v1/oauth/authorize?client_id=test"
                f"&state={state}&code_challenge={code_challenge}"
            )

    app.dependency_overrides[get_oauth_service] = lambda: StubOAuthService()
    try:
        response = client.get("/api/v1/auth/authorize-url")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith(
        "https://api.schwabapi.com/v1/oauth/authorize"
    )
    assert f"state={calls['state']}" in response.json()["authorization_url"]


def test_auth_start_redirects_to_schwab() -> None:
    calls: dict[str, str] = {}

    class StubOAuthService:
        def authorization_url(
            self,
            *,
            state: str | None = None,
            code_challenge: str | None = None,
            code_challenge_method: str | None = None,
        ) -> str:
            assert state
            assert code_challenge
            assert code_challenge_method == "S256"
            calls["state"] = state
            return (
                "https://api.schwabapi.com/v1/oauth/authorize?client_id=test"
                f"&state={state}&code_challenge={code_challenge}"
            )

    app.dependency_overrides[get_oauth_service] = lambda: StubOAuthService()
    try:
        response = client.get("/auth/start", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://api.schwabapi.com/v1/oauth/authorize")
    assert f"state={calls['state']}" in response.headers["location"]


def test_callback_endpoint_exchanges_code_and_saves_token() -> None:
    calls: dict[str, str] = {}
    saved: dict[str, OAuthToken] = {}

    class StubOAuthService:
        def authorization_url(
            self,
            *,
            state: str | None = None,
            code_challenge: str | None = None,
            code_challenge_method: str | None = None,
        ) -> str:
            assert state
            assert code_challenge
            assert code_challenge_method == "S256"
            calls["state"] = state
            return "https://api.schwabapi.com/v1/oauth/authorize?client_id=test"

        def exchange_authorization_code(
            self,
            code: str,
            *,
            code_verifier: str | None = None,
        ) -> OAuthToken:
            assert code == "code-123"
            assert code_verifier
            return OAuthToken(
                access_token="access-123",
                refresh_token="refresh-123",
                expires_in=1800,
            )

    class StubTokenStore:
        def save(self, token: OAuthToken) -> None:
            saved["token"] = token

    app.dependency_overrides[get_oauth_service] = lambda: StubOAuthService()
    app.dependency_overrides[get_token_store] = lambda: StubTokenStore()
    try:
        client.get("/auth/start", follow_redirects=False)
        response = client.get(
            f"/auth/callback?code=code-123&state={calls['state']}&session=session-xyz"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Schwab authorization completed."
    assert saved["token"].access_token == "access-123"


def test_exchange_code_endpoint_exchanges_code_and_saves_token() -> None:
    calls: dict[str, str] = {}
    saved: dict[str, OAuthToken] = {}

    class StubOAuthService:
        def authorization_url(
            self,
            *,
            state: str | None = None,
            code_challenge: str | None = None,
            code_challenge_method: str | None = None,
        ) -> str:
            assert state
            assert code_challenge
            assert code_challenge_method == "S256"
            calls["state"] = state
            return "https://api.schwabapi.com/v1/oauth/authorize?client_id=test"

        def exchange_authorization_code(
            self,
            code: str,
            *,
            code_verifier: str | None = None,
        ) -> OAuthToken:
            assert code == "manual-code-123"
            assert code_verifier
            return OAuthToken(
                access_token="access-123",
                refresh_token="refresh-123",
                expires_in=1800,
            )

    class StubTokenStore:
        def save(self, token: OAuthToken) -> None:
            saved["token"] = token

    app.dependency_overrides[get_oauth_service] = lambda: StubOAuthService()
    app.dependency_overrides[get_token_store] = lambda: StubTokenStore()
    try:
        client.get("/auth/start", follow_redirects=False)
        response = client.post(
            "/api/v1/auth/exchange-code",
            json={
                "code": "manual-code-123",
                "session": "session-xyz",
                "state": calls["state"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Schwab authorization completed."
    assert saved["token"].access_token == "access-123"


def test_callback_endpoint_rejects_schwab_error_responses() -> None:
    response = client.get(
        "/auth/callback?error=access_denied&error_description=User%20denied%20consent"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "User denied consent"


def test_auth_status_reports_presence_of_saved_token() -> None:
    class StubTokenStore:
        def load(self) -> OAuthToken:
            return OAuthToken(
                access_token="access-123",
                refresh_token="refresh-123",
                expires_in=1800,
            )

    app.dependency_overrides[get_token_store] = lambda: StubTokenStore()
    try:
        response = client.get("/api/v1/auth/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authenticated"] is True


def test_app_status_reports_setup_and_journal_state() -> None:
    now = "2026-04-14T20:30:00+00:00"

    class StubTokenStore:
        def load(self) -> OAuthToken:
            return OAuthToken(
                access_token="access-123",
                refresh_token="refresh-123",
                expires_in=1800,
            )

    class StubJournalStore:
        def get_overview(self) -> JournalOverview:
            return JournalOverview(
                account_count=1,
                order_count=2,
                transaction_count=3,
                last_sync=SyncRunSummary(
                    run_id="run-123",
                    started_at=now,
                    completed_at=now,
                    status=SyncRunStatus.SUCCESS,
                    orders_from=now,
                    orders_to=now,
                    transactions_from=now,
                    transactions_to=now,
                    accounts_synced=1,
                    orders_synced=2,
                    transactions_synced=3,
                ),
            )

    app.dependency_overrides[get_token_store] = lambda: StubTokenStore()
    app.dependency_overrides[get_journal_store] = lambda: StubJournalStore()
    try:
        response = client.get("/api/v1/app/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["journal_overview"]["account_count"] == 1


def test_accounts_sync_endpoint_requires_authorization() -> None:
    class StubBrokerService:
        def get_accounts(self, *, fields=None):
            raise RuntimeError("No Schwab token is stored. Complete OAuth authorization first.")

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        response = client.get("/api/v1/schwab/accounts?fields=positions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert (
        response.json()["detail"]
        == "No Schwab token is stored. Complete OAuth authorization first."
    )


def test_accounts_sync_endpoint_uses_broker_service() -> None:
    class StubBrokerService:
        def get_accounts(self, *, fields=None):
            assert fields == ["positions"]
            return [{"securitiesAccount": {"accountNumber": "..."}}]

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        response = client.get("/api/v1/schwab/accounts?fields=positions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [{"securitiesAccount": {"accountNumber": "..."}}]


def test_preview_order_endpoint_uses_broker_service() -> None:
    class StubBrokerService:
        def preview_order(self, *, account_hash, order_payload):
            assert account_hash == "abc123"
            assert order_payload["orderType"] == "LIMIT"
            return {"orderValidationResult": {"warns": []}}

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        response = client.post(
            "/api/v1/schwab/accounts/abc123/preview-order",
            json={"orderType": "LIMIT", "price": "189.50"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"orderValidationResult": {"warns": []}}


def test_journal_overview_endpoint_reads_local_store() -> None:
    now = "2026-04-14T20:30:00+00:00"

    class StubJournalStore:
        def get_overview(self) -> JournalOverview:
            return JournalOverview(
                account_count=1,
                order_count=2,
                transaction_count=3,
                last_sync=SyncRunSummary(
                    run_id="run-123",
                    started_at=now,
                    completed_at=now,
                    status=SyncRunStatus.SUCCESS,
                    orders_from=now,
                    orders_to=now,
                    transactions_from=now,
                    transactions_to=now,
                    accounts_synced=1,
                    orders_synced=2,
                    transactions_synced=3,
                ),
            )

    app.dependency_overrides[get_journal_store] = lambda: StubJournalStore()
    try:
        response = client.get("/api/v1/journal/overview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["account_count"] == 1
    assert response.json()["last_sync"]["status"] == "success"


def test_journal_orders_endpoint_passes_filters_to_store() -> None:
    class StubJournalStore:
        def list_orders(self, *, account_hash=None, limit=100):
            assert account_hash == "hash-123"
            assert limit == 25
            return [{"order_id": "101", "status": "FILLED"}]

    app.dependency_overrides[get_journal_store] = lambda: StubJournalStore()
    try:
        response = client.get("/api/v1/journal/orders?account_hash=hash-123&limit=25")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [{"order_id": "101", "status": "FILLED"}]


def test_journal_transactions_endpoint_passes_filters_to_store() -> None:
    class StubJournalStore:
        def list_transactions(self, *, account_hash=None, transaction_type=None, limit=100):
            assert account_hash == "hash-123"
            assert transaction_type == "TRADE"
            assert limit == 10
            return [{"transaction_id": "202", "transaction_type": "TRADE"}]

    app.dependency_overrides[get_journal_store] = lambda: StubJournalStore()
    try:
        response = client.get(
            "/api/v1/journal/transactions?account_hash=hash-123&transaction_type=TRADE&limit=10"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [{"transaction_id": "202", "transaction_type": "TRADE"}]


def test_journal_dashboard_route_serves_html() -> None:
    response = client.get("/api/v1/journal/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Local Journal Dashboard" in response.text


def test_rebuild_completed_trades_endpoint_reconstructs_and_persists(tmp_path) -> None:
    from datetime import UTC, datetime

    from schwab_trader.journal.store import SQLiteJournalStore

    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")
    synced_at = datetime(2026, 4, 14, 20, 30, tzinfo=UTC)
    store.upsert_orders(
        account_hash="hash-123",
        orders=[
            {
                "orderId": 1001,
                "orderLegCollection": [
                    {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                ],
            },
            {
                "orderId": 1002,
                "orderLegCollection": [
                    {"instruction": "SELL", "instrument": {"symbol": "AAPL"}},
                ],
            },
        ],
        synced_at=synced_at,
    )
    store.upsert_transactions(
        account_hash="hash-123",
        transactions=[
            {
                "activityId": 2001,
                "orderId": 1001,
                "type": "TRADE",
                "tradeDate": "2026-04-01T14:30:00.000Z",
                "netAmount": -1000,
                "transferItems": [
                    {
                        "amount": 10,
                        "price": 100,
                        "positionEffect": "OPENING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
            {
                "activityId": 2002,
                "orderId": 1002,
                "type": "TRADE",
                "tradeDate": "2026-04-03T14:30:00.000Z",
                "netAmount": 1100,
                "transferItems": [
                    {
                        "amount": 10,
                        "price": 110,
                        "positionEffect": "CLOSING",
                        "instrument": {"symbol": "AAPL"},
                    }
                ],
            },
        ],
        synced_at=synced_at,
    )

    app.dependency_overrides[get_journal_store] = lambda: store
    try:
        response = client.post("/api/v1/journal/rebuild-completed-trades")
        trades_response = client.get("/api/v1/journal/completed-trades")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["completed_trade_count"] == 1
    assert trades_response.status_code == 200
    assert trades_response.json()[0]["symbol"] == "AAPL"


def test_journal_scorecard_endpoint_returns_symbol_stats() -> None:
    now = "2026-04-14T20:30:00+00:00"

    class StubJournalStore:
        def list_completed_trades(self, *, account_hash=None, symbol=None, limit=500):
            assert account_hash is None
            assert symbol is None
            assert limit == 500
            return [
                {
                    "trade_id": "trade-1",
                    "account_hash": "hash-123",
                    "symbol": "AAPL",
                    "side": "long",
                    "quantity": 10,
                    "entry_price": 100,
                    "exit_price": 110,
                    "gross_pnl": 100,
                    "fees": 0,
                    "net_pnl": 100,
                    "entry_time": now,
                    "exit_time": now,
                    "hold_minutes": 60,
                    "benchmark_return_pct": 5,
                }
            ]

    app.dependency_overrides[get_journal_store] = lambda: StubJournalStore()
    try:
        response = client.get("/api/v1/journal/scorecard")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["summary"]["total_trades"] == 1
    assert response.json()["symbol_stats"][0]["symbol"] == "AAPL"


def test_journal_sync_endpoint_runs_sync_and_persists_data(tmp_path) -> None:
    from schwab_trader.journal.store import SQLiteJournalStore

    store = SQLiteJournalStore.from_database_url(f"sqlite:///{tmp_path / 'journal.db'}")

    class StubBrokerService:
        def get_account_numbers(self):
            return [{"accountNumber": "12345678", "hashValue": "hash-123"}]

        def get_account(self, account_hash, *, fields=None):
            assert account_hash == "hash-123"
            assert fields == ["positions"]
            return {"securitiesAccount": {"accountNumber": "12345678", "positions": []}}

        def get_orders_for_account(
            self,
            *,
            account_hash,
            from_entered_time,
            to_entered_time,
            max_results=None,
            status=None,
        ):
            assert account_hash == "hash-123"
            return [
                {
                    "orderId": 1001,
                    "orderLegCollection": [
                        {"instruction": "BUY", "instrument": {"symbol": "AAPL"}},
                    ],
                },
                {
                    "orderId": 1002,
                    "orderLegCollection": [
                        {"instruction": "SELL", "instrument": {"symbol": "AAPL"}},
                    ],
                },
            ]

        def get_transactions(
            self,
            *,
            account_hash,
            start_date,
            end_date,
            types,
            symbol=None,
        ):
            assert account_hash == "hash-123"
            assert "TRADE" in types
            return [
                {
                    "activityId": 2001,
                    "orderId": 1001,
                    "type": "TRADE",
                    "tradeDate": "2026-04-01T14:30:00.000Z",
                    "netAmount": -1000,
                    "transferItems": [
                        {
                            "amount": 10,
                            "price": 100,
                            "positionEffect": "OPENING",
                            "instrument": {"symbol": "AAPL"},
                        }
                    ],
                },
                {
                    "activityId": 2002,
                    "orderId": 1002,
                    "type": "TRADE",
                    "tradeDate": "2026-04-03T14:30:00.000Z",
                    "netAmount": 1100,
                    "transferItems": [
                        {
                            "amount": 10,
                            "price": 110,
                            "positionEffect": "CLOSING",
                            "instrument": {"symbol": "AAPL"},
                        }
                    ],
                },
            ]

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    app.dependency_overrides[get_journal_store] = lambda: store
    try:
        response = client.post("/api/v1/journal/sync?days=30")
        trades_response = client.get("/api/v1/journal/completed-trades")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["accounts_synced"] == 1
    assert trades_response.status_code == 200
    assert trades_response.json()[0]["symbol"] == "AAPL"
