from datetime import UTC, datetime, timedelta

from schwab_trader.auth.models import OAuthToken
from schwab_trader.broker.service import SchwabBrokerService


class InMemoryTokenStore:
    def __init__(self, token: OAuthToken | None) -> None:
        self.token = token
        self.saved: OAuthToken | None = None

    def load(self) -> OAuthToken | None:
        return self.token

    def save(self, token: OAuthToken) -> None:
        self.token = token
        self.saved = token


class StubOAuthService:
    def __init__(self, refreshed_token: OAuthToken) -> None:
        self.refreshed_token = refreshed_token
        self.refresh_calls = 0

    def refresh_access_token(self, refresh_token: str) -> OAuthToken:
        assert refresh_token == "refresh-123"
        self.refresh_calls += 1
        return self.refreshed_token


class StubClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self.closed = False

    def get_account_numbers(self) -> list[dict]:
        return [{"hashValue": self.access_token}]

    def close(self) -> None:
        self.closed = True


def test_broker_service_refreshes_expired_tokens_before_read_only_calls() -> None:
    expired = OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-123",
        expires_in=60,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    refreshed = OAuthToken(
        access_token="fresh-access",
        refresh_token="refresh-123",
        expires_in=1800,
        created_at=datetime.now(UTC),
    )
    store = InMemoryTokenStore(expired)
    oauth = StubOAuthService(refreshed)

    service = SchwabBrokerService(
        token_store=store,
        oauth_service=oauth,
        client_factory=StubClient,
    )

    payload = service.get_account_numbers()

    assert oauth.refresh_calls == 1
    assert store.saved is not None
    assert store.saved.access_token == "fresh-access"
    assert payload == [{"hashValue": "fresh-access"}]
