from fastapi.testclient import TestClient

from schwab_trader.auth.models import OAuthToken
from schwab_trader.server.app import app
from schwab_trader.server.dependencies import get_oauth_service, get_token_store

client = TestClient(app)


def test_auth_start_generates_state_and_pkce_then_callback_consumes_it() -> None:
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
            calls["code_challenge"] = code_challenge
            return (
                "https://api.schwabapi.com/v1/oauth/authorize"
                f"?state={state}&code_challenge={code_challenge}"
                "&code_challenge_method=S256"
            )

        def exchange_authorization_code(
            self, code: str, *, code_verifier: str | None = None
        ) -> OAuthToken:
            assert code == "code-123"
            assert code_verifier
            calls["code_verifier"] = code_verifier
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
        start = client.get("/auth/start", follow_redirects=False)
        callback = client.get(f"/auth/callback?code=code-123&state={calls['state']}")
    finally:
        app.dependency_overrides.clear()

    assert start.status_code == 307
    assert "code_challenge=" in start.headers["location"]
    assert callback.status_code == 200
    assert saved["token"].access_token == "access-123"
    assert calls["code_verifier"]


def test_callback_rejects_unknown_state() -> None:
    response = client.get("/auth/callback?code=code-123&state=missing-state")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired OAuth state."


def test_manual_exchange_uses_pending_auth_session_when_state_is_omitted() -> None:
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
            calls["state"] = state or ""
            return "https://api.schwabapi.com/v1/oauth/authorize"

        def exchange_authorization_code(
            self, code: str, *, code_verifier: str | None = None
        ) -> OAuthToken:
            assert code == "manual-code-123"
            assert code_verifier
            calls["code_verifier"] = code_verifier
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
            json={"code": "manual-code-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert saved["token"].access_token == "access-123"
    assert calls["code_verifier"]
