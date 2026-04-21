import re

from fastapi.testclient import TestClient

from schwab_trader.agent.store import AlertStore
from schwab_trader.server.app import app
from schwab_trader.server.dependencies import get_broker_service
from schwab_trader.server.routes import agent as agent_routes

client = TestClient(app)


def _proposal(*, proposal_id: str = "proposal-123", approval_token: str = "approve-123") -> dict:
    return {
        "id": proposal_id,
        "symbol": "NVDA",
        "action": "BUY",
        "quantity": 5.0,
        "order_type": "LIMIT",
        "limit_price": 100.0,
        "reasoning": "High-conviction setup.",
        "urgency": "MEDIUM",
        "status": "pending",
        "approval_token": approval_token,
        "denial_token": "deny-123",
        "token_expires_at": "2099-01-01T00:00:00+00:00",
    }


def _alert(proposal: dict) -> dict:
    return {
        "id": "alert-123",
        "timestamp": "2026-04-19T12:00:00+00:00",
        "alert_type": "BUY_SCAN",
        "flags": [],
        "claude_analysis": None,
        "proposals": [proposal],
        "portfolio_value": 10_000,
        "status": "pending",
        "sms_sent": False,
        "email_sent": False,
    }


def _install_store(monkeypatch, tmp_path, proposal: dict) -> AlertStore:
    store = AlertStore(tmp_path / ".alerts.json")
    store.save_alert(_alert(proposal))
    monkeypatch.setattr(agent_routes, "_store", store)
    return store


def test_trade_approval_get_renders_confirmation_without_placing_order(
    monkeypatch, tmp_path
) -> None:
    _install_store(monkeypatch, tmp_path, _proposal())

    class StubBrokerService:
        def place_order(self, *, account_hash, order_payload):
            raise AssertionError("GET approval page must not place live orders")

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        response = client.get("/trade/approve/approve-123")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Review Before Execution" in response.text
    assert "confirmApproval()" in response.text


def test_trade_approval_post_previews_then_places_order(monkeypatch, tmp_path) -> None:
    _install_store(monkeypatch, tmp_path, _proposal())
    calls = {"preview": 0, "place": 0}

    class StubBrokerService:
        def get_primary_account_hash(self) -> str:
            return "acct-123"

        def get_account(self, account_hash: str, *, fields=None) -> dict:
            assert account_hash == "acct-123"
            return {
                "securitiesAccount": {
                    "currentBalances": {
                        "liquidationValue": 20_000,
                        "cashAvailableForTrading": 10_000,
                        "cashBalance": 10_000,
                        "currentDayProfitLoss": 0,
                    },
                    "positions": [],
                }
            }

        def preview_order(self, *, account_hash, order_payload):
            calls["preview"] += 1
            assert account_hash == "acct-123"
            assert order_payload["orderType"] == "LIMIT"
            return {"orderValidationResult": {"warns": []}}

        def place_order(self, *, account_hash, order_payload):
            calls["place"] += 1
            assert calls["preview"] == 1
            assert account_hash == "acct-123"
            assert order_payload["orderType"] == "LIMIT"

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        approval_page = client.get("/trade/approve/approve-123")
        match = re.search(r'"confirm_token":"([^"]+)"', approval_page.text)
        assert match is not None

        response = client.post(
            "/trade/approve/approve-123",
            json={"confirm_token": match.group(1)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Trade Executed" in response.text
    assert calls == {"preview": 1, "place": 1}


def test_execute_proposal_blocks_when_risk_checks_fail(monkeypatch, tmp_path) -> None:
    proposal = _proposal(proposal_id="proposal-risk")
    proposal["quantity"] = 30.0
    proposal["limit_price"] = 100.0
    _install_store(monkeypatch, tmp_path, proposal)

    class StubBrokerService:
        def get_primary_account_hash(self) -> str:
            return "acct-123"

        def get_account(self, account_hash: str, *, fields=None) -> dict:
            return {
                "securitiesAccount": {
                    "currentBalances": {
                        "liquidationValue": 20_000,
                        "cashAvailableForTrading": 20_000,
                        "cashBalance": 20_000,
                        "currentDayProfitLoss": 0,
                    },
                    "positions": [],
                }
            }

        def preview_order(self, *, account_hash, order_payload):
            raise AssertionError("Risk-blocked executions must not preview")

        def place_order(self, *, account_hash, order_payload):
            raise AssertionError("Risk-blocked executions must not place live orders")

    app.dependency_overrides[get_broker_service] = lambda: StubBrokerService()
    try:
        response = client.post("/api/v1/agent/proposals/proposal-risk/execute")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "Order notional exceeds the configured cap." in response.json()["detail"]
