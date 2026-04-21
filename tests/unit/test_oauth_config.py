from schwab_trader.auth.oauth import OAuthConfig


def test_authorization_url_matches_confirmed_schwab_flow() -> None:
    config = OAuthConfig(
        client_id="client-id-123",
        client_secret="secret-123",
        redirect_uri="https://developer.schwab.com/oauth2-redirect.html",
        scope="readonly",
    )

    assert (
        config.authorization_url()
        == "https://api.schwabapi.com/v1/oauth/authorize"
        "?response_type=code"
        "&client_id=client-id-123"
        "&scope=readonly"
        "&redirect_uri=https%3A%2F%2Fdeveloper.schwab.com%2Foauth2-redirect.html"
    )
    assert config.token_url == "https://api.schwabapi.com/v1/oauth/token"


def test_authorization_url_can_include_state_and_pkce_parameters() -> None:
    config = OAuthConfig(
        client_id="client-id-123",
        client_secret="secret-123",
        redirect_uri="https://developer.schwab.com/oauth2-redirect.html",
        scope="readonly",
    )

    url = config.authorization_url(
        state="state-123",
        code_challenge="challenge-456",
        code_challenge_method="S256",
    )

    assert "state=state-123" in url
    assert "code_challenge=challenge-456" in url
    assert "code_challenge_method=S256" in url
