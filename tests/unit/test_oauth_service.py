from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from schwab_trader.auth.models import OAuthToken
from schwab_trader.auth.oauth import OAuthConfig
from schwab_trader.auth.service import SchwabOAuthService
from schwab_trader.auth.token_store import FileTokenStore


def test_exchange_authorization_code_posts_form_with_basic_auth() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = request.content.decode()
        return httpx.Response(
            status_code=200,
            json={
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "expires_in": 1800,
                "scope": "readonly",
                "token_type": "Bearer",
            },
        )

    service = SchwabOAuthService(
        config=OAuthConfig(
            client_id="client-id-123",
            client_secret="secret-123",
            redirect_uri="https://localhost:8443/auth/callback",
        ),
        transport=httpx.MockTransport(handler),
    )

    token = service.exchange_authorization_code("code-123")

    assert captured["url"] == "https://api.schwabapi.com/v1/oauth/token"
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["body"] == (
        "grant_type=authorization_code&code=code-123"
        "&redirect_uri=https%3A%2F%2Flocalhost%3A8443%2Fauth%2Fcallback"
    )
    assert captured["auth"].startswith("Basic ")
    assert token.access_token == "access-123"
    assert token.refresh_token == "refresh-123"


def test_exchange_authorization_code_includes_code_verifier_when_provided() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(
            status_code=200,
            json={
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "expires_in": 1800,
                "scope": "readonly",
                "token_type": "Bearer",
            },
        )

    service = SchwabOAuthService(
        config=OAuthConfig(
            client_id="client-id-123",
            client_secret="secret-123",
            redirect_uri="https://localhost:8443/auth/callback",
        ),
        transport=httpx.MockTransport(handler),
    )

    service.exchange_authorization_code("code-123", code_verifier="verifier-xyz")

    assert "code_verifier=verifier-xyz" in captured["body"]


def test_refresh_access_token_preserves_existing_refresh_token() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "access_token": "access-456",
                "expires_in": 1800,
                "scope": "readonly",
                "token_type": "Bearer",
            },
        )

    service = SchwabOAuthService(
        config=OAuthConfig(
            client_id="client-id-123",
            client_secret="secret-123",
            redirect_uri="https://localhost:8443/auth/callback",
        ),
        transport=httpx.MockTransport(handler),
    )

    token = service.refresh_access_token("refresh-123")

    assert token.access_token == "access-456"
    assert token.refresh_token == "refresh-123"


def test_file_token_store_round_trip(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path / "tokens.json")
    token = OAuthToken(
        access_token="access-123",
        refresh_token="refresh-123",
        expires_in=1800,
        created_at=datetime.now(UTC),
    )

    store.save(token)
    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "access-123"
    assert loaded.refresh_token == "refresh-123"


def test_oauth_token_expiry_detection_uses_expires_in() -> None:
    token = OAuthToken(
        access_token="access-123",
        refresh_token="refresh-123",
        expires_in=60,
        created_at=datetime.now(UTC) - timedelta(minutes=2),
    )

    assert token.is_access_token_expired() is True
